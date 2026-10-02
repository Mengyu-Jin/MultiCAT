"""CrossRef DOI search module (no API key required).

CrossRef API: https://api.crossref.org/works
Uses the query parameter for full-text search, complementing Scopus/OpenAlex.
"""
from __future__ import annotations

import os
import time
import requests


_BASE_URL = "https://api.crossref.org/works"
_EMAIL = os.environ.get("CONTACT_EMAIL", "")  # contact address for the API polite pool

_PROFILE_QUERIES: dict[str, str] = {
    "lactic_acid": (
        "lactic acid heterogeneous catalyst biomass glucose fructose cellulose"
    ),
    "levulinic_acid": (
        "levulinic acid heterogeneous catalyst biomass glucose cellulose"
    ),
    "furfural": (
        "furfural heterogeneous catalyst xylose hemicellulose biomass"
    ),
    "c5_sugar": (
        "furfural xylose hemicellulose heterogeneous catalyst solid acid"
    ),
    "bimetallic": (
        "bimetallic catalyst biomass glucose fructose HMF furfural lactic acid"
    ),
    "default": (
        "heterogeneous catalyst biomass glucose fructose xylose cellulose "
        "HMF furfural lactic acid levulinic acid"
    ),
}


def search_crossref(profile_name: str, limit: int = 0) -> list[dict]:
    """Search CrossRef and return a list of {doi, title, journal, year}."""
    query = _PROFILE_QUERIES.get(profile_name, _PROFILE_QUERIES["default"])
    results: list[dict] = []
    offset = 0
    rows = 100
    max_retries = 3

    print(f"  Searching CrossRef (profile={profile_name}, limit={limit or 'unlimited'})...")

    while True:
        params = {
            "query": query,
            "filter": "type:journal-article",
            "rows": rows if limit == 0 else min(rows, limit - len(results)),
            "offset": offset,
            "select": "DOI,title,container-title,published,published-print,published-online",
            "mailto": _EMAIL,
        }

        resp = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(_BASE_URL, params=params, timeout=30)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt >= max_retries:
                    raise RuntimeError("CrossRef API request failed") from exc
                time.sleep(2 ** attempt)

        assert resp is not None
        data = resp.json()
        message = data.get("message", {})
        items = message.get("items", [])
        total = message.get("total-results", 0)

        if not items:
            break

        for item in items:
            doi = item.get("DOI", "").strip()
            if not doi:
                continue
            title = item.get("title", [""])[0] if item.get("title") else ""
            journal = ""
            ct = item.get("container-title")
            if ct:
                journal = ct[0] if isinstance(ct, list) else ct
            # Prefer published, then published-print, then published-online
            year = ""
            for key in ("published", "published-print", "published-online"):
                dp = item.get(key, {}).get("date-parts")
                if dp and dp[0]:
                    year = str(dp[0][0])
                    break
            results.append({"doi": doi, "title": title, "journal": journal, "year": year})

        print(f"  Got {len(results)} results so far (total available: {total})")

        if limit > 0 and len(results) >= limit:
            results = results[:limit]
            break

        offset += len(items)
        if offset >= total:
            break

        time.sleep(0.5)

    return results
