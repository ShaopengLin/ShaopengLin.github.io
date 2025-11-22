---
layout: page
permalink: /publications/
title: Publications
description:
nav: true
nav_order: 2
---

<!-- _pages/publications.md -->

<!-- Bibsearch Feature -->

{% include bib_search.liquid %}

<div class="publications">

<h1>Preprints</h1>

{% bibliography -f preprints %}

<h1>Conferences</h1>

{% bibliography -f papers %}

<h1>Workshops</h1>

{% bibliography -f workshops %}

</div>
