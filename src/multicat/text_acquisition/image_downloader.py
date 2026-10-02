"""Download figure images for accepted papers.

Supports:
  - Elsevier: Full-Text Retrieval API (objects endpoint) → gr1.jpg, gr2.jpg …
  - Springer OA: image URLs embedded in JATS XML or constructed from DOI
  - RSC: pubs.rsc.org image CDN

Images are saved to papers/<pid>/images/<locator_or_figid>.<ext>

Usage:
    python -m multicat.text_acquisition.image_downloader
    python -m multicat.text_acquisition.image_downloader --paper-id P000003
    python -m multicat.text_acquisition.image_downloader --wanted-only
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import NamedTuple

import requests


class ImageResult(NamedTuple):
    fig_id: str
    locator: str | None
    saved_path: Path | None
    ok: bool
    error: str


# ---------------------------------------------------------------------------
# Elsevier
# ---------------------------------------------------------------------------

def _elsevier_object_url(doi: str, locator: str) -> str:
    """Build Elsevier Full-Text object URL for a figure locator like gr1."""
    encoded_doi = doi.replace("/", "%2F")
    return f"https://api.elsevier.com/content/object/eid/1-s2.0-{encoded_doi}-{locator}"


def _download_elsevier_images(
    doi: str,
    figure_captions: list[dict],
    images_dir: Path,
    api_key: str,
    wanted_ids: set[str] | None,
    session: requests.Session,
    timeout: int,
) -> list[ImageResult]:
    """Download Elsevier figures via the object retrieval endpoint."""
    results = []
    headers = {
        "X-ELS-APIKey": api_key,
        "Accept": "image/jpeg, image/png, image/*",
    }

    # First try: fetch full-text XML with ?view=FULL to get object URLs
    ft_url = f"https://api.elsevier.com/content/article/doi/{doi}?view=FULL"
    object_urls: dict[str, str] = {}  # locator → absolute URL
    try:
        r = session.get(ft_url, headers={**headers, "Accept": "application/json"}, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            objects = (
                data.get("full-text-retrieval-response", {})
                .get("objects", {})
                .get("object", [])
            )
            if isinstance(objects, dict):
                objects = [objects]
            for obj in objects:
                ref = obj.get("@ref", "")
                url = obj.get("$", "") or obj.get("#text", "")
                if ref and url:
                    object_urls[ref] = url
    except Exception:
        pass  # fallback to constructed URL below

    for fc in figure_captions:
        fig_id = fc.get("id", "")
        locator = fc.get("locator")
        if not locator:
            results.append(ImageResult(fig_id, locator, None, False, "no_locator"))
            continue
        if wanted_ids is not None and fig_id not in wanted_ids:
            continue

        # Check already downloaded
        existing = _find_existing(images_dir, locator)
        if existing:
            results.append(ImageResult(fig_id, locator, existing, True, ""))
            continue

        # Try URL from full-text JSON first, then constructed fallback
        url = object_urls.get(locator) or _elsevier_object_url(doi, locator)

        try:
            r = session.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                ext = _content_type_to_ext(r.headers.get("Content-Type", ""))
                out = images_dir / f"{locator}{ext}"
                out.write_bytes(r.content)
                results.append(ImageResult(fig_id, locator, out, True, ""))
            else:
                results.append(ImageResult(fig_id, locator, None, False, f"HTTP {r.status_code}"))
        except Exception as exc:
            results.append(ImageResult(fig_id, locator, None, False, str(exc)))

        time.sleep(0.5)

    return results


# ---------------------------------------------------------------------------
# Springer OA (JATS XML contains <graphic> xlink:href)
# ---------------------------------------------------------------------------

def _download_springer_images(
    doi: str,
    figure_captions: list[dict],
    xml_path: Path,
    images_dir: Path,
    api_key: str,
    wanted_ids: set[str] | None,
    session: requests.Session,
    timeout: int,
) -> list[ImageResult]:
    import xml.etree.ElementTree as ET

    results = []
    # Parse XML to find graphic href per fig id
    href_by_figid: dict[str, str] = {}
    try:
        root = ET.parse(xml_path).getroot()
        ns = {"xlink": "http://www.w3.org/1999/xlink"}
        for fig in root.iter("fig"):
            fid = fig.get("id", "")
            graphic = fig.find(".//graphic")
            if graphic is not None:
                href = graphic.get("{http://www.w3.org/1999/xlink}href", "")
                if href:
                    href_by_figid[fid] = href
    except Exception:
        pass

    for fc in figure_captions:
        fig_id = fc.get("id", "")
        if wanted_ids is not None and fig_id not in wanted_ids:
            continue

        existing = _find_existing(images_dir, fig_id)
        if existing:
            results.append(ImageResult(fig_id, None, existing, True, ""))
            continue

        href = href_by_figid.get(fig_id, "")
        if not href:
            results.append(ImageResult(fig_id, None, None, False, "no_graphic_href"))
            continue

        # Springer OA images: full URL or relative path
        if href.startswith("http"):
            url = href
        else:
            url = f"https://media.springernature.com/full/springer-static/{href}"

        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 200:
                ext = _content_type_to_ext(r.headers.get("Content-Type", ""))
                out = images_dir / f"{fig_id}{ext}"
                out.write_bytes(r.content)
                results.append(ImageResult(fig_id, None, out, True, ""))
            else:
                results.append(ImageResult(fig_id, None, None, False, f"HTTP {r.status_code}"))
        except Exception as exc:
            results.append(ImageResult(fig_id, None, None, False, str(exc)))

        time.sleep(0.5)

    return results


# ---------------------------------------------------------------------------
# RSC (pubs.rsc.org)
# ---------------------------------------------------------------------------

def _download_rsc_images(
    doi: str,
    figure_captions: list[dict],
    xml_path: Path,
    images_dir: Path,
    wanted_ids: set[str] | None,
    session: requests.Session,
    timeout: int,
) -> list[ImageResult]:
    import xml.etree.ElementTree as ET

    results = []
    href_by_figid: dict[str, str] = {}
    try:
        root = ET.parse(xml_path).getroot()
        for fig in root.iter("fig"):
            fid = fig.get("id", "")
            graphic = fig.find(".//graphic")
            if graphic is not None:
                href = graphic.get("{http://www.w3.org/1999/xlink}href", "")
                if href:
                    href_by_figid[fid] = href
    except Exception:
        pass

    for fc in figure_captions:
        fig_id = fc.get("id", "")
        if wanted_ids is not None and fig_id not in wanted_ids:
            continue

        existing = _find_existing(images_dir, fig_id)
        if existing:
            results.append(ImageResult(fig_id, None, existing, True, ""))
            continue

        href = href_by_figid.get(fig_id, "")
        if not href:
            results.append(ImageResult(fig_id, None, None, False, "no_graphic_href"))
            continue

        if href.startswith("http"):
            url = href
        else:
            url = f"https://pubs.rsc.org/en/content/image/{href}"

        try:
            r = session.get(url, timeout=timeout,
                            headers={"Referer": f"https://pubs.rsc.org/en/content/articlelanding/{doi}"})
            if r.status_code == 200:
                ext = _content_type_to_ext(r.headers.get("Content-Type", ""))
                out = images_dir / f"{fig_id}{ext}"
                out.write_bytes(r.content)
                results.append(ImageResult(fig_id, None, out, True, ""))
            else:
                results.append(ImageResult(fig_id, None, None, False, f"HTTP {r.status_code}"))
        except Exception as exc:
            results.append(ImageResult(fig_id, None, None, False, str(exc)))

        time.sleep(0.5)

    return results


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def download_images_for_paper(
    paper_dir: Path,
    elsevier_api_key: str = "",
    springer_api_key: str = "",
    wanted_only: bool = True,
    timeout: int = 30,
) -> list[ImageResult]:
    """Download all (or only wanted) figures for a single paper."""
    pkg_path = paper_dir / "03_text_package.json"
    sc_path = paper_dir / "06_screening.json"
    xml_path = paper_dir / "01_paper.xml"

    if not pkg_path.exists():
        return []

    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    figure_captions = pkg.get("figure_captions", [])
    if not figure_captions:
        return []

    wanted_ids: set[str] | None = None
    if wanted_only and sc_path.exists():
        sc = json.loads(sc_path.read_text(encoding="utf-8"))
        fl = sc.get("figure_labels", {})
        wanted_ids = {fid for fid, label in fl.items() if label == "wanted"}
        if not wanted_ids:
            return []

    images_dir = paper_dir / "images"
    images_dir.mkdir(exist_ok=True)

    xml_type = pkg.get("xml_type", "")
    doi = pkg.get("metadata", {}).get("doi", "")

    session = requests.Session()
    session.headers["User-Agent"] = f"multicat/1.0 (research; mailto:{os.environ.get('CONTACT_EMAIL', '')})"

    if xml_type == "elsevier" and elsevier_api_key:
        return _download_elsevier_images(
            doi, figure_captions, images_dir, elsevier_api_key,
            wanted_ids, session, timeout,
        )

    if xml_type == "jats" and xml_path.exists():
        doi_lower = doi.lower()
        if "springer" in doi_lower or doi.startswith("10.1007") or doi.startswith("10.1038"):
            return _download_springer_images(
                doi, figure_captions, xml_path, images_dir,
                springer_api_key, wanted_ids, session, timeout,
            )
        if doi.startswith("10.1039"):  # RSC
            return _download_rsc_images(
                doi, figure_captions, xml_path, images_dir,
                wanted_ids, session, timeout,
            )

    return []


# ---------------------------------------------------------------------------
# Batch CLI
# ---------------------------------------------------------------------------

def _find_existing(images_dir: Path, name: str) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff"):
        p = images_dir / f"{name}{ext}"
        if p.exists():
            return p
    return None


def _content_type_to_ext(ct: str) -> str:
    ct = ct.lower().split(";")[0].strip()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/tiff": ".tif",
    }.get(ct, ".jpg")


def run_batch(
    papers_root: Path,
    project_root: Path,
    *,
    wanted_only: bool = True,
    force: bool = False,
    paper_ids: list[str] | None = None,
) -> None:
    from multicat.text_acquisition.env_utils import load_dotenv_keys
    load_dotenv_keys(project_root)

    elsevier_api_key = os.environ.get("ELSEVIER_API_KEY", "")
    springer_api_key = os.environ.get("SPRINGER_OPENACCESS_API_KEY", "")

    if paper_ids:
        candidates = [papers_root / pid for pid in paper_ids]
    else:
        candidates = sorted(p for p in papers_root.iterdir() if p.is_dir())

    # filter to accepted papers
    targets = []
    for p in candidates:
        sc_path = p / "06_screening.json"
        if not sc_path.exists():
            continue
        sc = json.loads(sc_path.read_text(encoding="utf-8"))
        if sc.get("decision") != "keep":
            continue
        if not force and (p / "images").exists() and any((p / "images").iterdir()):
            continue
        targets.append(p)

    print(f"Papers to download images for: {len(targets)}")
    total_ok = total_fail = total_skip = 0

    for i, paper_dir in enumerate(targets, 1):
        paper_id = paper_dir.name
        print(f"[{i}/{len(targets)}] {paper_id}", flush=True)
        try:
            results = download_images_for_paper(
                paper_dir,
                elsevier_api_key=elsevier_api_key,
                springer_api_key=springer_api_key,
                wanted_only=wanted_only,
            )
            ok = sum(1 for r in results if r.ok)
            fail = sum(1 for r in results if not r.ok)
            skip = 0
            if not results:
                skip = 1
            print(f"  ok={ok} fail={fail}" + (" (no results/unsupported)" if skip else ""))
            total_ok += ok
            total_fail += fail
            total_skip += skip
        except Exception as exc:
            print(f"  ERROR: {exc}")
            total_fail += 1

    print(f"\nDone. images_ok={total_ok} images_fail={total_fail} papers_skipped={total_skip}")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Download figure images for accepted papers")
    parser.add_argument("--papers-root", default="papers")
    parser.add_argument("--paper-id", nargs="*", help="Specific paper IDs")
    parser.add_argument("--all-figures", action="store_true", help="Download all figures, not just wanted")
    parser.add_argument("--force", action="store_true", help="Re-download even if images dir exists")
    args = parser.parse_args()

    project_root = Path.cwd()
    papers_root = project_root / args.papers_root

    run_batch(
        papers_root,
        project_root,
        wanted_only=not args.all_figures,
        force=args.force,
        paper_ids=args.paper_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
