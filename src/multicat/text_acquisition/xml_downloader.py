from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class XmlDownloadConfig:
    elsevier_api_key: str = ""
    springer_api_key: str = ""
    elsevier_fulltext_url: str = "https://api.elsevier.com/content/article/doi"
    pmc_id_converter_url: str = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
    pmc_fetch_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    springer_jats_url: str = "https://api.springernature.com/openaccess/jats"
    tool_name: str = "multicat"
    email: str = "multicat@example.com"
    timeout: int = 60


@dataclass(frozen=True)
class XmlDownloadResult:
    success: bool
    source: str
    xml_text: str
    status: str
    error: str = ""


def is_elsevier_doi(doi: str) -> bool:
    return doi.lower().startswith("10.1016/")


def download_xml_for_doi(doi: str, config: XmlDownloadConfig, http_client) -> XmlDownloadResult:
    if is_elsevier_doi(doi) and config.elsevier_api_key:
        result = _fetch_elsevier(doi, config, http_client)
        if result.success:
            return result

    pmcid = _doi_to_pmcid(doi, config, http_client)
    if pmcid:
        result = _fetch_pmc(pmcid, config, http_client)
        if result.success:
            return result

    if config.springer_api_key:
        result = _fetch_springer_oa(doi, config, http_client)
        if result.success:
            return result

    return XmlDownloadResult(
        success=False,
        source="",
        xml_text="",
        status="fail",
        error="No structured XML available from Elsevier, PMC, or Springer OA.",
    )


def _fetch_elsevier(doi: str, config: XmlDownloadConfig, http_client) -> XmlDownloadResult:
    response = http_client.get(
        f"{config.elsevier_fulltext_url}/{doi}",
        headers={
            "X-ELS-APIKey": config.elsevier_api_key,
            "Accept": "text/xml",
        },
        timeout=config.timeout,
    )
    if response.status_code != 200:
        return _failure(f"Elsevier HTTP {response.status_code}")

    text = response.text
    if "<full-text-retrieval-response" in text and ("<ce:sections" in text or "<ce:para" in text):
        return XmlDownloadResult(True, "elsevier", text, "success")
    return _failure("Elsevier response did not contain full-text XML body")


def _doi_to_pmcid(doi: str, config: XmlDownloadConfig, http_client) -> str | None:
    response = http_client.get(
        config.pmc_id_converter_url,
        params={
            "ids": doi,
            "format": "json",
            "tool": config.tool_name,
            "email": config.email,
        },
        timeout=30,
    )
    if response.status_code != 200:
        return None
    records = response.json().get("records", [])
    if records and records[0].get("pmcid"):
        return records[0]["pmcid"]
    return None


def _fetch_pmc(pmcid: str, config: XmlDownloadConfig, http_client) -> XmlDownloadResult:
    response = http_client.get(
        config.pmc_fetch_url,
        params={
            "db": "pmc",
            "id": pmcid.replace("PMC", ""),
            "rettype": "xml",
            "tool": config.tool_name,
            "email": config.email,
        },
        timeout=config.timeout,
    )
    if response.status_code != 200:
        return _failure(f"PMC HTTP {response.status_code}")
    if "<article" in response.text or "<pmc-articleset" in response.text:
        return XmlDownloadResult(True, "pmc", response.text, "success")
    return _failure("PMC response did not contain JATS XML")


def _fetch_springer_oa(doi: str, config: XmlDownloadConfig, http_client) -> XmlDownloadResult:
    response = http_client.get(
        config.springer_jats_url,
        params={"q": f"doi:{doi}", "api_key": config.springer_api_key},
        timeout=config.timeout,
    )
    if response.status_code != 200:
        return _failure(f"Springer OA HTTP {response.status_code}")
    if "<article" in response.text or "<articles" in response.text:
        return XmlDownloadResult(True, "springer_oa", response.text, "success")
    return _failure("Springer OA response did not contain JATS XML")


def _failure(error: str) -> XmlDownloadResult:
    return XmlDownloadResult(False, "", "", "fail", error)
