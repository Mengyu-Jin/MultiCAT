from __future__ import annotations

import argparse
import os
from pathlib import Path

import requests

from multicat.text_acquisition.env_utils import load_dotenv_keys
from multicat.text_acquisition.xml_downloader import (
    XmlDownloadConfig,
    download_xml_for_doi,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch structured XML for one DOI.")
    parser.add_argument("--doi", required=True)
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--output-root", default="papers")
    args = parser.parse_args()

    project_root = Path.cwd()
    load_dotenv_keys(project_root)

    config = XmlDownloadConfig(
        elsevier_api_key=os.environ.get("ELSEVIER_API_KEY", ""),
        springer_api_key=os.environ.get("SPRINGER_OPENACCESS_API_KEY", "")
        or os.environ.get("SPRINGER_API_KEY", ""),
    )
    result = download_xml_for_doi(args.doi, config, requests)

    if not result.success:
        print(f"xml_status=fail source=none error={result.error}")
        return 1

    paper_dir = Path(args.output_root) / args.paper_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    xml_path = paper_dir / "01_paper.xml"
    xml_path.write_text(result.xml_text, encoding="utf-8")
    print(f"xml_status=success source={result.source} path={xml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
