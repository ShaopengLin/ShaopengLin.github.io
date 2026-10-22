#!/usr/bin/env python3
"""Update citation badges from a Scholar profile or a browser-saved HTML page."""

import argparse
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path):
    with path.open(encoding="utf-8") as source:
        data = yaml.safe_load(source)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return data


def profile_url(user_id, start=0):
    return "https://scholar.google.com/citations?" + urlencode(
        {"user": user_id, "hl": "en", "pagesize": 100, "cstart": start}
    )


def parse_profile(html, user_id):
    """Return validated publication data and whether another page is available."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("tr.gsc_a_tr")
    if not rows:
        raise ValueError(
            "No publication rows found. Scholar may have returned a CAPTCHA, "
            "sign-in page, or changed its markup."
        )
    papers = {}
    for row in rows:
        title = row.select_one("a.gsc_a_at")
        count = row.select_one("a.gsc_a_ac")
        year = row.select_one(".gsc_a_y")
        if title is None or count is None or year is None:
            raise ValueError("Incomplete publication row; refusing to save partial data.")
        query = parse_qs(urlparse(title.get("href", "")).query)
        pub_id = query.get("citation_for_view", [""])[0]
        if not re.fullmatch(re.escape(user_id) + r":[\w-]+", pub_id):
            raise ValueError(f"Publication ID {pub_id!r} does not match profile {user_id}.")
        if pub_id in papers:
            raise ValueError(f"Duplicate publication ID: {pub_id}")
        # Scholar displays an empty link for zero and sometimes appends an asterisk.
        count_text = count.get_text(strip=True).removesuffix("*").strip()
        if count_text and not re.fullmatch(r"[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+", count_text):
            raise ValueError(f"Unrecognized citation count {count_text!r} for {pub_id}.")
        paper_title = title.get_text(" ", strip=True)
        if not paper_title:
            raise ValueError(f"Missing title for {pub_id}.")
        papers[pub_id] = {
            "title": paper_title,
            "year": year.get_text(strip=True) or "Unknown Year",
            "citations": int(count_text.replace(",", "") or "0"),
        }
    more = soup.select_one("#gsc_bpf_more")
    if more is None:
        raise ValueError("Missing pagination control; cannot verify that the profile is complete.")
    return papers, not more.has_attr("disabled")


def fetch_citations(user_id):
    papers = {}
    for _ in range(20):
        url = profile_url(user_id, len(papers))
        print(f"Fetching {url}", flush=True)
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"})
        with urlopen(request, timeout=30) as response:
            page, has_more = parse_profile(response.read(), user_id)
        if papers.keys() & page.keys():
            raise ValueError("Scholar repeated a page; refusing to save incomplete data.")
        papers.update(page)
        if not has_more:
            return papers
    raise ValueError("Profile exceeded 20 pages; refusing to save incomplete data.")


def update_citations(papers, output, dry_run=False):
    existing = load_yaml(output) if output.exists() else {}
    old_papers = existing.get("papers", {})
    if not isinstance(old_papers, dict):
        raise ValueError(f"Invalid papers mapping in {output}")
    missing = old_papers.keys() - papers.keys()
    if missing:
        raise ValueError(
            "Previously saved publications are missing: " + ", ".join(sorted(missing))
            + ". Load all publications before importing. If Scholar merged or removed "
            "a paper, review and remove its old YAML entry manually first."
        )
    if old_papers == papers:
        print("No changes in citation data. Skipping file update.")
        return False
    for pub_id, paper in papers.items():
        old_count = old_papers.get(pub_id, {}).get("citations", "new")
        print(f"{paper['title']}: {old_count} -> {paper['citations']}")
    if dry_run:
        print(f"Dry run: would update {output}")
        return True
    data = {
        "metadata": {"last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
        "papers": papers,
    }
    # Replace only after the entire profile has been fetched and validated.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as dest:
            temporary = Path(dest.name)
            yaml.safe_dump(data, dest, width=1000, sort_keys=True, allow_unicode=True)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Citation data saved to {output}. Review the diff before committing.")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-html", type=Path, help="Import a complete profile saved as HTML; makes no network requests")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing the citation file")
    args = parser.parse_args(argv)
    try:
        user_id = load_yaml(ROOT / "_data/socials.yml").get("scholar_userid")
        if not isinstance(user_id, str) or not re.fullmatch(r"[\w-]+", user_id):
            raise ValueError("Set scholar_userid in _data/socials.yml to your Google Scholar user ID.")
        if args.from_html:
            papers, has_more = parse_profile(args.from_html.read_bytes(), user_id)
            if has_more:
                raise ValueError("Saved profile is incomplete. Click 'Show more' until all papers are visible, then save again.")
        else:
            papers = fetch_citations(user_id)
        update_citations(papers, ROOT / "_data/citations.yml", args.dry_run)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"Citation update failed: {error}", file=sys.stderr)
        print(
            "Existing citation data was not changed. If Scholar blocks requests, open your "
            "profile in a browser, save the full page as HTML, then run "
            "bin/update_scholar_citations.py --from-html /path/to/profile.html. "
            "See docs/citations.md.", file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
