"""PMC full-text search module: returns only articles that have full-text XML in PMC.

Uses the NCBI E-utilities API (free, no key required; a contact email is recommended).
Searches the PMC full-text database directly, so every result can be downloaded as XML.
"""
from __future__ import annotations

import os
import time
import requests

_BASE_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_BASE_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_EMAIL = os.environ.get("CONTACT_EMAIL", "")  # contact address for the API polite pool

_PROFILE_QUERIES: dict[str, str] = {
    "lactic_acid": (
        '("lactic acid" OR "glycolic acid" OR "acetic acid")'
        ' AND (zeolite OR "solid acid" OR "metal oxide" OR "ion exchange resin")'
        ' AND (glucose OR cellulose OR biomass OR fructose OR xylose)'
    ),
    "lactic_acid_v2": (
        '("lactic acid" OR "pyruvic acid")'
        ' AND ("Sn-Beta" OR "Lewis acid" OR "retro-aldol" OR hydrotalcite OR "solid base")'
        ' AND (glucose OR fructose OR cellulose)'
    ),
    "levulinic_acid": (
        '("levulinic acid" OR "formic acid")'
        ' AND (zeolite OR "solid acid" OR "metal oxide" OR "supported catalyst")'
        ' AND (glucose OR cellulose OR furfural OR biomass)'
    ),
    "furfural": (
        'furfural AND (zeolite OR "solid acid" OR "metal oxide" OR "ion exchange resin")'
        ' AND (xylose OR hemicellulose OR biomass OR "corn cob" OR bagasse)'
    ),
    "c5_sugar": (
        '(xylose OR hemicellulose OR arabinose)'
        ' AND (zeolite OR "solid acid" OR "heterogeneous catalyst")'
        ' AND (furfural OR "lactic acid")'
    ),
    "no_product_filter": (
        '(glucose OR fructose OR xylose OR cellulose OR hemicellulose OR biomass)'
        ' AND (zeolite OR "solid acid" OR "metal oxide" OR "heterogeneous catalyst")'
    ),
    "zeolite_biomass": (
        '(zeolite OR "ZSM-5" OR "Beta zeolite" OR "MCM-41" OR "SBA-15")'
        ' AND (glucose OR cellulose OR biomass)'
        ' AND (HMF OR furfural OR "lactic acid" OR "levulinic acid")'
    ),
    "solid_acid_catalyst": (
        '("solid acid" OR "Bronsted acid" OR "Lewis acid" OR "heteropolyacid" OR "sulfated zirconia")'
        ' AND (glucose OR fructose OR cellulose OR xylose OR biomass)'
        ' AND (HMF OR furfural OR "lactic acid" OR "levulinic acid" OR "acetic acid")'
    ),
    "biomass_hydrothermal": (
        '(hydrothermal OR "subcritical water" OR "hot compressed water")'
        ' AND (glucose OR cellulose OR biomass OR xylose OR hemicellulose)'
        ' AND ("lactic acid" OR "acetic acid" OR HMF OR furfural OR "levulinic acid")'
    ),
    "dehydration_reaction": (
        '(glucose OR fructose OR xylose OR cellulose OR biomass)'
        ' AND (zeolite OR "solid acid" OR "heterogeneous catalyst")'
        ' AND (dehydration OR isomerization OR conversion OR "C-C cleavage")'
    ),
    "default": (
        '(glucose OR cellulose OR biomass)'
        ' AND ("heterogeneous catalyst" OR zeolite OR "solid acid")'
        ' AND (HMF OR furfural OR "lactic acid" OR "levulinic acid")'
    ),
}


def search_pmc(profile_name: str, limit: int = 0) -> list[dict]:
    """Search the PMC full-text database and return only articles with full-text XML."""
    query = _PROFILE_QUERIES.get(profile_name, _PROFILE_QUERIES["default"])

    print(f"  Searching PMC (profile={profile_name}, limit={limit or 'unlimited'})...")

    # Step 1: esearch to get the list of PMCIDs
    all_pmcids: list[str] = []
    retstart = 0
    retmax = 500

    while True:
        params = {
            "db": "pmc",
            "term": query,
            "retstart": retstart,
            "retmax": retmax,
            "retmode": "json",
            "email": _EMAIL,
        }
        for attempt in range(1, 4):
            try:
                resp = requests.get(_BASE_ESEARCH, params=params, timeout=30)
                resp.raise_for_status()
                break
            except requests.RequestException:
                if attempt >= 3:
                    raise
                time.sleep(2 ** attempt)

        data = resp.json().get("esearchresult", {})
        ids = data.get("idlist", [])
        total = int(data.get("count", 0))

        all_pmcids.extend(ids)
        print(f"  Got {len(all_pmcids)} PMCIDs so far (total available: {total})")

        if not ids or (limit > 0 and len(all_pmcids) >= limit):
            break
        retstart += len(ids)
        if retstart >= total:
            break
        time.sleep(0.34)  # NCBI rate limit: 3 requests per second

    if limit > 0:
        all_pmcids = all_pmcids[:limit]

    if not all_pmcids:
        return []

    # Step 2: esummary to fetch DOIs in batches
    results: list[dict] = []
    batch_size = 200
    for i in range(0, len(all_pmcids), batch_size):
        batch = all_pmcids[i:i + batch_size]
        params = {
            "db": "pmc",
            "id": ",".join(batch),
            "retmode": "json",
            "email": _EMAIL,
        }
        for attempt in range(1, 4):
            try:
                resp = requests.get(_BASE_ESUMMARY, params=params, timeout=30)
                resp.raise_for_status()
                break
            except requests.RequestException:
                if attempt >= 3:
                    raise
                time.sleep(2 ** attempt)

        summary = resp.json().get("result", {})
        for pmcid in batch:
            item = summary.get(pmcid, {})
            # The DOI is in the articleids list
            doi = ""
            for aid in item.get("articleids", []):
                if aid.get("idtype") == "doi":
                    doi = aid.get("value", "").strip()
                    break
            if not doi:
                continue
            results.append({
                "doi": doi,
                "title": item.get("title", ""),
                "journal": item.get("source", ""),
                "year": str(item.get("pubdate", "")[:4]),
            })
        time.sleep(0.34)

    print(f"  PMC search done: {len(results)} DOIs with full-text XML")
    return results
