"""OpenAlex DOI search module (no API key required).

OpenAlex API: https://api.openalex.org/works
Builds the query with full-text search (title + abstract), complementing Scopus.
"""
from __future__ import annotations

import os
import time
import requests


_BASE_URL = "https://api.openalex.org/works"
_EMAIL = os.environ.get("CONTACT_EMAIL", "")  # contact address for the API polite pool


def build_openalex_query(profile_name: str) -> dict:
    """Return OpenAlex search API parameters (filter + search).

    OpenAlex does not support complex nested Boolean queries, so filter=title_and_abstract.search is used
    for keyword matching, and the Screening Agent does the precise filtering.
    """
    # Product keywords (specific to each profile)
    _PRODUCT_QUERIES: dict[str, str] = {
        "lactic_acid": '"lactic acid" OR "lactate" OR "glycolic acid" OR "acetic acid"',
        "levulinic_acid": '"levulinic acid" OR "angelica lactone" OR "GVL"',
        "furfural": "furfural OR furfuraldehyde",
        "c5_sugar": "furfural OR xylose OR hemicellulose",
        "bimetallic": (
            '"lactic acid" OR HMF OR furfural OR "levulinic acid"'
            ' OR "formic acid" OR "acetic acid"'
        ),
        "default": (
            '"lactic acid" OR "5-hydroxymethylfurfural" OR HMF OR furfural'
            ' OR "levulinic acid" OR "formic acid" OR "acetic acid" OR "glycolic acid"'
        ),
    }

    # Substrate keywords (shared)
    substrate = (
        "glucose OR fructose OR xylose OR cellulose OR sucrose OR hemicellulose"
        ' OR "wheat straw" OR bagasse OR "corn stover" OR "rice straw"'
        " OR starch OR mannose OR galactose OR arabinose OR cellobiose"
        ' OR "lignocellulosic biomass" OR "real biomass"'
    )

    # Catalyst keywords (no restriction on metals, only broad heterogeneous catalyst classes)
    catalyst = (
        '"heterogeneous catalyst" OR zeolite OR "solid acid" OR "metal oxide"'
        ' OR "ion exchange resin" OR MOF OR "solid base"'
        ' OR "supported catalyst" OR "carbon catalyst" OR "bifunctional catalyst"'
    )

    product = _PRODUCT_QUERIES.get(profile_name, _PRODUCT_QUERIES["default"])

    # Exclude homogeneous catalysts, fermentation, reviews, and downstream hydrogenation routes
    exclude = (
        'NOT homogeneous NOT fermentation NOT enzymatic NOT review NOT survey'
        ' NOT hydrogenation NOT photocatalysis NOT electrocatalysis'
    )

    search_str = f"({substrate}) AND ({catalyst}) AND ({product}) {exclude}"

    return {
        "search": search_str,
        "filter": "type:article,is_retracted:false",
        "select": "doi,title,primary_location,publication_year",
        "sort": "relevance_score:desc",
        "per-page": 200,
        "mailto": _EMAIL,
    }


def search_openalex(profile_name: str, limit: int = 0) -> list[dict]:
    """Search OpenAlex and return a list of {doi, title, journal, year}.

    Publishers are not prefiltered; xml_downloader tries each download itself,
    and papers from Elsevier, Springer, PMC OA, Wiley OA, and others with XML access succeed.
    """
    params = build_openalex_query(profile_name)
    results: list[dict] = []
    cursor = "*"
    max_retries = 3

    print(f"  Searching OpenAlex (profile={profile_name}, limit={limit or 'unlimited'})...")

    while True:
        page_params = dict(params)
        page_params["cursor"] = cursor
        page_params["per-page"] = 200

        resp = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(_BASE_URL, params=page_params, timeout=30)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt >= max_retries:
                    raise RuntimeError("OpenAlex API request failed") from exc
                time.sleep(2 ** attempt)

        assert resp is not None
        data = resp.json()
        meta = data.get("meta", {})
        works = data.get("results", [])
        total = meta.get("count", 0)

        if not works:
            break

        for w in works:
            doi = w.get("doi")
            if not doi:
                continue
            doi = doi.replace("https://doi.org/", "").strip()
            loc = w.get("primary_location") or {}
            source = loc.get("source") or {}
            results.append({
                "doi": doi,
                "title": w.get("title", ""),
                "journal": source.get("display_name", ""),
                "year": str(w.get("publication_year", "")),
            })

        print(f"  Got {len(results)} results so far (total available: {total})")

        if limit > 0 and len(results) >= limit:
            results = results[:limit]
            break

        next_cursor = meta.get("next_cursor")
        if not next_cursor:
            break
        cursor = next_cursor
        time.sleep(0.2)

    return results
