"""Scopus DOI search for biomass carbohydrate heterogeneous catalysis papers.

Builds a Scopus Search API query from config.yaml, retrieves
DOI + title + journal + year, and appends new records to
paper_registry.csv. It does not fetch or store abstracts in the registry -- paper_registry.csv
keeps its existing 14-column shape for backward compatibility, and the
Screening Agent already reads the abstract from 03_text_package.json
(parsed from the full XML during Text Acquisition), so a duplicate
abstract field in the registry is not needed.

This is a rule-based Text Acquisition module, not an LLM agent.
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

import requests
import yaml

from multicat.text_acquisition.env_utils import load_dotenv_keys

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def raise_api_error(resp: requests.Response, source: str) -> None:
    if resp.status_code >= 400:
        raise RuntimeError(f"{source} HTTP {resp.status_code}")


def load_config(project_root: Path) -> dict:
    load_dotenv_keys(project_root)
    config_path = project_root / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config["elsevier"]["api_key"] = os.environ.get("ELSEVIER_API_KEY", "")
    return config


SEARCH_PROFILES: dict[str, dict[str, str]] = {
    # Default config.yaml query_substrate is dominated by C6 sugar terms
    # (glucose/fructose/sucrose/cellobiose/...), which in practice returns
    # ~5x more C6 hits than C5 (xylose/mannose/galactose/arabinose) and
    # essentially zero lactic_acid/acetic_acid/glycolic_acid product hits
    # (observed: 184 hmf_yield rows vs 0 for those three products in the
    # first 24-paper batch). These profiles narrow the substrate/product
    # query to the underrepresented terms so a dedicated search batch can
    # target them directly, instead of being drowned out by C6/HMF papers
    # in a single combined query.
    "c5_sugar": {
        "query_substrate": (
            'xylose OR mannose OR galactose OR arabinose OR xylan'
            ' OR hemicellulose OR "wheat straw" OR "corn stover" OR bagasse'
            ' OR "rice straw" OR "rice husk" OR switchgrass OR "corn cob"'
        ),
        "query_product": (
            '"lactic acid" OR "5-hydroxymethylfurfural" OR HMF OR furfural'
            ' OR "levulinic acid" OR "formic acid" OR "acetic acid" OR "glycolic acid"'
        ),
        "query_catalyst": (
            '"heterogeneous catalyst" OR zeolite OR "metal oxide" OR "solid acid"'
            ' OR "ion-exchange resin" OR MOF OR "carbon-based catalyst"'
            ' OR "supported catalyst" OR niobium OR zirconium OR tin OR titanium'
            ' OR chromium OR tungsten OR iron OR "bimetallic catalyst"'
        ),
    },
    "lactic_acid": {
        "query_product": '"lactic acid" OR "acetic acid" OR "glycolic acid" OR "formic acid"',
        "query_substrate": (
            # C6 monosaccharides and synonyms
            'glucose OR dextrose OR fructose OR "D-fructose" OR sucrose OR'
            ' cellobiose OR lactose OR maltose OR trehalose OR mannose OR galactose'
            # C5 monosaccharides and synonyms
            ' OR xylose OR "D-xylose" OR "wood sugar" OR arabinose OR ribose'
            # Polysaccharides and oligosaccharides
            ' OR cellulose OR microcellulose OR "microcrystalline cellulose"'
            ' OR starch OR "corn starch" OR "potato starch" OR xylan OR hemicellulose OR inulin'
            # Real biomass (several expressions)
            ' OR "wheat straw" OR "corn stover" OR "corn cob" OR "corn husk" OR "corn stalk"'
            ' OR bagasse OR "sugarcane bagasse" OR "sugar cane bagasse"'
            ' OR "rice straw" OR "rice husk" OR "rice bran"'
            ' OR sawdust OR "wood sawdust" OR "poplar" OR "birch" OR "bamboo"'
            ' OR switchgrass OR "energy grass"'
            ' OR "lignocellulosic biomass" OR "lignocellulose" OR "real biomass"'
            ' OR "agricultural waste" OR "agricultural residue"'
        ),
        "query_catalyst": (
            '"heterogeneous catalyst" OR zeolite OR "metal oxide" OR "solid acid"'
            ' OR "ion-exchange resin" OR MOF OR "carbon-based catalyst"'
            ' OR "supported catalyst" OR "solid base" OR "bifunctional catalyst"'
        ),
    },
    "metal_catalyst": {
        "query_catalyst": (
            '"metal oxide" OR "supported metal" OR "metal-loaded catalyst"'
            ' OR niobium OR tantalum OR zirconium OR tin OR titanium OR iron'
            ' OR chromium OR tungsten OR "bimetallic catalyst"'
            ' OR vanadium OR molybdenum OR copper OR zinc OR cerium'
        ),
        "query_substrate": (
            'glucose OR fructose OR sucrose OR cellobiose OR lactose OR maltose'
            ' OR xylose OR mannose OR galactose OR arabinose'
            ' OR cellulose OR starch OR xylan OR hemicellulose'
            ' OR "wheat straw" OR "corn stover" OR bagasse OR "rice straw"'
            ' OR "lignocellulosic biomass" OR "real biomass"'
        ),
        "query_product": (
            '"lactic acid" OR "5-hydroxymethylfurfural" OR HMF OR furfural'
            ' OR "levulinic acid" OR "formic acid" OR "acetic acid" OR "glycolic acid"'
        ),
    },
    "lactic_acid_v2": {
        "query_product": '"lactic acid" OR "lactate" OR "glycolic acid" OR "acetic acid"',
        "query_substrate": (
            'glucose OR fructose OR sucrose OR cellulose OR starch'
            ' OR xylose OR mannose OR arabinose OR galactose'
            ' OR "dihydroxyacetone" OR "pyruvaldehyde" OR "methylglyoxal"'
            ' OR "triose" OR "hexose"'
            ' OR "wheat straw" OR "corn stover" OR bagasse OR "rice straw"'
            ' OR "lignocellulosic biomass"'
        ),
        "query_catalyst": (
            '"Sn-Beta" OR "Sn-BEA" OR "Sn-MFI" OR "SnO2" OR "ZnO"'
            ' OR hydrotalcite OR "MgAl" OR "Bi2WO6" OR "AlW"'
            ' OR "retro-aldol" OR "isomerization" OR "C-C cleavage"'
            ' OR "Lewis acid" OR "Brønsted acid" OR "solid base"'
            ' OR "alkaline catalyst" OR "base catalyst"'
            ' OR niobium OR zirconium OR tin OR titanium OR zinc OR bismuth'
        ),
    },
    "bimetallic": {
        "query_catalyst": (
            '"bimetallic catalyst" OR bimetallic OR "alloy catalyst" OR "binary metal"'
            ' OR "dual metal" OR "bifunctional metal catalyst"'
            ' OR "Cu-Zn" OR "Ni-Fe" OR "Cu-Fe" OR "Ni-Co" OR "Zn-Fe"'
            ' OR "Mo-V" OR "Cr-V" OR "W-V" OR "Cu-Cr" OR "Ni-Cu"'
            ' OR "Fe-Co" OR "Zn-Cu" OR "Ce-Zr" OR "Ti-Zr" OR "Sn-Zr"'
        ),
        "query_substrate": (
            'glucose OR fructose OR sucrose OR cellobiose OR lactose OR maltose'
            ' OR xylose OR mannose OR galactose OR arabinose'
            ' OR cellulose OR starch OR xylan OR hemicellulose'
            ' OR "wheat straw" OR "corn stover" OR bagasse OR "rice straw"'
            ' OR "lignocellulosic biomass" OR "real biomass"'
        ),
        "query_product": (
            '"lactic acid" OR "5-hydroxymethylfurfural" OR HMF OR furfural'
            ' OR "levulinic acid" OR "formic acid" OR "acetic acid" OR "glycolic acid"'
        ),
    },
    "no_product_filter": {
        # No product restriction: search catalyst and substrate only, covering all possible products
        "query_catalyst": (
            '"heterogeneous catalyst" OR zeolite OR "solid acid" OR "metal oxide"'
            ' OR "ion exchange resin" OR "supported catalyst" OR "bifunctional catalyst"'
            ' OR "carbon catalyst" OR MOF OR hydrotalcite OR "solid base"'
        ),
        "query_substrate": (
            'glucose OR fructose OR sucrose OR cellulose OR starch OR xylose'
            ' OR mannose OR arabinose OR hemicellulose OR xylan OR inulin'
            ' OR "wheat straw" OR "corn stover" OR bagasse OR "rice straw"'
            ' OR "corn cob" OR sawdust OR "lignocellulosic biomass" OR "real biomass"'
            ' OR "agricultural waste" OR chitosan OR chitin'
        ),
        "query_product": "",  # no product restriction
    },
    "dehydration_reaction": {
        # Organized by reaction type: dehydration, isomerization, retro-aldol, oxidation
        "query_catalyst": (
            '"heterogeneous catalyst" OR zeolite OR "solid acid" OR "metal oxide"'
            ' OR "supported catalyst" OR "ion exchange resin"'
        ),
        "query_substrate": (
            'glucose OR fructose OR xylose OR cellulose OR sucrose OR starch'
            ' OR hemicellulose OR "lignocellulosic biomass" OR bagasse OR "corn stover"'
        ),
        "query_product": (
            'dehydration OR isomerization OR "retro-aldol" OR oxidation'
            ' OR "C-C cleavage" OR "ring opening" OR conversion'
        ),
    },
    "zeolite_biomass": {
        # Specifically for zeolite catalysts and biomass substrates
        "query_catalyst": (
            'zeolite OR "ZSM-5" OR "Beta zeolite" OR "Y zeolite" OR "MCM-41"'
            ' OR "SBA-15" OR "MFI" OR "BEA" OR "FAU" OR "mordenite"'
            ' OR "dealuminated" OR "hierarchical zeolite" OR "mesoporous zeolite"'
        ),
        "query_substrate": (
            'glucose OR fructose OR sucrose OR cellulose OR starch OR xylose'
            ' OR mannose OR arabinose OR hemicellulose OR "lignocellulosic biomass"'
            ' OR bagasse OR "wheat straw" OR "corn stover" OR "real biomass"'
        ),
        "query_product": (
            '"lactic acid" OR "acetic acid" OR "glycolic acid" OR "formic acid"'
            ' OR "levulinic acid" OR HMF OR furfural OR "pyruvic acid"'
        ),
    },
    "solid_acid_catalyst": {
        # Organized by catalyst type, covering all products
        "query_catalyst": (
            '"solid acid" OR "Brønsted acid" OR "Lewis acid" OR "superacid"'
            ' OR "acid catalyst" OR "acidic resin" OR "sulfated zirconia"'
            ' OR "phosphotungstic acid" OR "silicotungstic acid" OR "heteropolyacid"'
            ' OR "H-ZSM-5" OR "H-Beta" OR "H-Y zeolite" OR "HZSM-5"'
            ' OR "niobic acid" OR "Nb2O5" OR "WO3" OR "MoO3"'
        ),
        "query_substrate": (
            'glucose OR fructose OR sucrose OR cellulose OR starch'
            ' OR xylose OR mannose OR arabinose OR hemicellulose OR xylan'
            ' OR "wheat straw" OR "corn stover" OR bagasse OR "rice straw"'
            ' OR "lignocellulosic biomass" OR "real biomass"'
        ),
        "query_product": (
            '"lactic acid" OR "acetic acid" OR "glycolic acid" OR "formic acid"'
            ' OR "levulinic acid" OR HMF OR furfural'
        ),
    },
    "biomass_hydrothermal": {
        # Organized by the hydrothermal reaction method
        "query_catalyst": (
            'hydrothermal OR "subcritical water" OR "hot compressed water"'
            ' OR "alkaline hydrothermal" OR "acid hydrothermal"'
            ' OR "microwave-assisted" OR "solvent-free"'
        ),
        "query_substrate": (
            'glucose OR fructose OR sucrose OR cellulose OR starch'
            ' OR xylose OR mannose OR arabinose OR hemicellulose'
            ' OR "wheat straw" OR "corn stover" OR bagasse OR "rice straw"'
            ' OR "lignocellulosic biomass" OR "real biomass" OR chitosan OR chitin'
        ),
        "query_product": (
            '"lactic acid" OR "acetic acid" OR "glycolic acid" OR "formic acid"'
            ' OR "levulinic acid" OR HMF OR furfural'
        ),
    },
    "levulinic_acid": {
        "query_product": '"levulinic acid" OR "acetic acid" OR "glycolic acid" OR "formic acid"',
        "query_substrate": (
            'glucose OR fructose OR cellulose OR sucrose OR cellobiose OR maltose'
            ' OR xylose OR mannose OR galactose OR arabinose'
            ' OR starch OR xylan OR hemicellulose OR inulin'
            ' OR "real biomass" OR "lignocellulosic biomass"'
            ' OR "corn stover" OR "wheat straw" OR bagasse OR "rice straw"'
            ' OR "rice husk" OR sawdust'
        ),
        "query_catalyst": (
            '"heterogeneous catalyst" OR zeolite OR "metal oxide" OR "solid acid"'
            ' OR "ion-exchange resin" OR MOF OR "carbon-based catalyst"'
            ' OR "supported catalyst" OR niobium OR zirconium OR tin OR titanium'
            ' OR chromium OR tungsten OR iron OR "bimetallic catalyst"'
        ),
    },
}


def build_query(config: dict, profile: str | None = None) -> str:
    """Build the Scopus search query from config.yaml's scopus section.

    Structure mirrors the keep/skip conditions of the Screening Agent:
    substrate AND catalyst AND product AND experimental-evidence,
    minus fermentation/polyol/downstream-route/other-energy/
    thermochemical/review exclusions.

    `profile`, if given, overrides one or more of the substrate/catalyst/
    product query fields with a narrower set of terms (see SEARCH_PROFILES)
    to target an underrepresented slice of the dataset in its own search
    batch, without changing the default config.yaml query used otherwise.
    """
    scopus = dict(config["scopus"])
    if profile:
        overrides = SEARCH_PROFILES[profile]
        scopus.update(overrides)
    product_clause = (
        f" AND TITLE-ABS-KEY({scopus['query_product']})"
        if scopus.get("query_product") else ""
    )
    query = (
        f"TITLE-ABS-KEY({scopus['query_substrate']})"
        f" AND TITLE-ABS-KEY({scopus['query_catalyst']})"
        f"{product_clause}"
        f" AND TITLE-ABS-KEY({scopus['query_experimental']})"
        f" AND NOT TITLE-ABS-KEY({scopus['query_exclude_fermentation']})"
        f" AND NOT TITLE-ABS-KEY({scopus['query_exclude_polyol']})"
        f" AND NOT TITLE-ABS-KEY({scopus['query_exclude_downstream']})"
        f" AND NOT TITLE-ABS-KEY({scopus['query_exclude_other_energy']})"
        f" AND NOT TITLE-ABS-KEY({scopus['query_exclude_thermochemical']})"
        f" AND NOT TITLE({scopus['query_exclude_review']})"
        f" AND DOCTYPE(ar)"
    )
    return query


def search_scopus(config: dict, query: str, limit: int) -> list[dict]:
    """Call the Scopus Search API, return a list of DOI/title/journal/year records."""
    url = config["elsevier"]["search_url"]
    api_key = config["elsevier"]["api_key"]
    results: list[dict] = []
    count = 25
    max_retries = 3
    start = 0

    while True:
        params = {
            "query": query,
            "apiKey": api_key,
            "start": start,
            "count": min(count, limit - len(results)) if limit > 0 else count,
            "field": "dc:identifier,dc:title,prism:publicationName,prism:coverDate,prism:doi",
            "sort": "relevance",
            "view": "STANDARD",
        }

        print(f"  Searching Scopus: start={start}, requesting {params['count']} results...")
        resp = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.get(url, params=params, timeout=30)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    wait_seconds = 2**attempt
                    print(
                        f"  Scopus transient HTTP {resp.status_code}; "
                        f"retrying in {wait_seconds}s ({attempt}/{max_retries})..."
                    )
                    time.sleep(wait_seconds)
                    continue
                raise_api_error(resp, "Scopus Search API")
                break
            except requests.RequestException as exc:
                if attempt >= max_retries:
                    raise RuntimeError("Scopus Search API request failed") from exc
                wait_seconds = 2**attempt
                print(f"  Scopus request failed; retrying in {wait_seconds}s ({attempt}/{max_retries})...")
                time.sleep(wait_seconds)
        assert resp is not None
        data = resp.json()

        search_results = data.get("search-results", {})
        total_results = int(search_results.get("opensearch:totalResults", 0))
        entries = search_results.get("entry", [])

        if not entries or (len(entries) == 1 and "error" in entries[0]):
            print(f"  No more results. Total available: {total_results}")
            break

        for entry in entries:
            doi = entry.get("prism:doi")
            if not doi:
                continue
            results.append(
                {
                    "doi": doi,
                    "title": entry.get("dc:title", ""),
                    "journal": entry.get("prism:publicationName", ""),
                    "year": entry.get("prism:coverDate", "")[:4],
                }
            )

        print(f"  Got {len(results)} results so far (total available: {total_results})")

        if limit > 0 and len(results) >= limit:
            results = results[:limit]
            break

        start += len(entries)
        if start >= total_results:
            break

        time.sleep(1.0 / config["elsevier"]["rate_limit_per_second"])

    return results


def load_existing_dois(registry_path: Path) -> set[str]:
    existing: set[str] = set()
    if registry_path.exists():
        with registry_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("doi"):
                    existing.add(row["doi"].strip().lower())
    return existing


def get_next_paper_id(registry_path: Path) -> int:
    max_id = 0
    if registry_path.exists():
        with registry_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = row.get("paper_id", "")
                if pid.startswith("P"):
                    try:
                        max_id = max(max_id, int(pid[1:]))
                    except ValueError:
                        pass
    return max_id + 1


REGISTRY_COLUMNS = [
    "paper_id",
    "doi",
    "title",
    "journal",
    "year",
    "publisher",
    "xml_url",
    "xml_source",
    "xml_status",
    "md_status",
    "tables_count",
    "screening_decision",
    "pipeline_status",
    "notes",
]


def append_to_registry(registry_path: Path, records: list[dict]) -> None:
    file_has_data = registry_path.exists() and registry_path.stat().st_size > 0
    mode = "a" if file_has_data else "w"
    with registry_path.open(mode, encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_COLUMNS)
        if not file_has_data:
            writer.writeheader()
        for rec in records:
            writer.writerow({column: rec.get(column, "") for column in REGISTRY_COLUMNS})


def deduplicate_against_registry(results: list[dict], existing_dois: set[str]) -> list[dict]:
    """Filter out DOIs already in the registry, and also drop duplicates
    that appear more than once within `results` itself.

    Scopus pagination can return the same DOI twice across pages (observed
    in practice: 10.1016/j.chemosphere.2023.140126 came back as two separate
    entries within one search call). `existing_dois` must be updated as we
    go, not just checked once, so within-batch duplicates are also caught.
    """
    new_results = []
    for r in results:
        doi_key = r["doi"].strip().lower()
        if doi_key in existing_dois:
            continue
        existing_dois.add(doi_key)
        new_results.append(r)
    return new_results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search Scopus for biomass carbohydrate heterogeneous catalysis papers."
    )
    parser.add_argument("--limit", type=int, default=10, help="Max results (0=unlimited)")
    parser.add_argument("--registry-path", default="registry/paper_registry.csv")
    parser.add_argument(
        "--profile",
        choices=sorted(SEARCH_PROFILES.keys()),
        default=None,
        help="Narrow the search to an underrepresented slice (see SEARCH_PROFILES) "
        "instead of the default config.yaml query.",
    )
    args = parser.parse_args()

    config = load_config(PROJECT_ROOT)
    registry_path = PROJECT_ROOT / args.registry_path

    existing_dois = load_existing_dois(registry_path)
    next_id = get_next_paper_id(registry_path)

    print(f"Registry: {registry_path}")
    print(f"Existing DOIs: {len(existing_dois)}")
    print(f"Next Paper ID: P{next_id:06d}")
    if args.profile:
        print(f"Profile: {args.profile}")
    print()

    query = build_query(config, profile=args.profile)
    print(f"Query: {query[:200]}...")
    print()

    results = search_scopus(config, query, args.limit)
    print(f"Retrieved: {len(results)} results")

    new_results = deduplicate_against_registry(results, existing_dois)
    print(f"New (not in registry): {len(new_results)}")

    if not new_results:
        print("Nothing new to add.")
        return 0

    notes = f"scopus_search:{args.profile}" if args.profile else "scopus_search"
    records = []
    for rec in new_results:
        paper_id = f"P{next_id:06d}"
        records.append(
            {
                "paper_id": paper_id,
                "doi": rec["doi"],
                "title": rec["title"],
                "journal": rec["journal"],
                "year": rec["year"],
                "publisher": "",
                "xml_url": "",
                "xml_source": "",
                "xml_status": "",
                "md_status": "",
                "tables_count": "",
                "screening_decision": "",
                "pipeline_status": "",
                "notes": notes,
            }
        )
        next_id += 1

    append_to_registry(registry_path, records)
    print(f"Written {len(records)} records to registry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
