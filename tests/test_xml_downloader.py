from multicat.text_acquisition.xml_downloader import (
    XmlDownloadConfig,
    download_xml_for_doi,
    is_elsevier_doi,
)


class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        return self._json_data


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("No fake response configured")
        return self.responses.pop(0)


def test_is_elsevier_doi_matches_101016_prefix_only():
    assert is_elsevier_doi("10.1016/j.apcatb.2024.124000")
    assert not is_elsevier_doi("10.1038/s41598-025-17712-9")


def test_download_xml_for_elsevier_doi_uses_elsevier_first():
    client = FakeHttpClient(
        [
            FakeResponse(
                text="<full-text-retrieval-response><ce:sections><ce:para>Body</ce:para></ce:sections></full-text-retrieval-response>"
            )
        ]
    )
    config = XmlDownloadConfig(elsevier_api_key="elsevier-key")

    result = download_xml_for_doi("10.1016/j.example.2024.1", config, client)

    assert result.success is True
    assert result.source == "elsevier"
    assert "full-text-retrieval-response" in result.xml_text
    assert len(client.calls) == 1
    assert client.calls[0][1]["headers"]["Accept"] == "text/xml"


def test_download_xml_for_non_elsevier_uses_pmc_when_pmcid_exists():
    client = FakeHttpClient(
        [
            FakeResponse(json_data={"records": [{"pmcid": "PMC1234567"}]}),
            FakeResponse(text="<article><body><sec><p>PMC body</p></sec></body></article>"),
        ]
    )
    config = XmlDownloadConfig()

    result = download_xml_for_doi("10.1038/example", config, client)

    assert result.success is True
    assert result.source == "pmc"
    assert "PMC body" in result.xml_text
    assert "idconv" in client.calls[0][0]
    assert "efetch.fcgi" in client.calls[1][0]


def test_download_xml_falls_back_to_springer_when_pmc_unavailable():
    client = FakeHttpClient(
        [
            FakeResponse(json_data={"records": [{}]}),
            FakeResponse(text="<articles><article><body><sec><p>Springer body</p></sec></body></article></articles>"),
        ]
    )
    config = XmlDownloadConfig(springer_api_key="springer-key")

    result = download_xml_for_doi("10.1007/example", config, client)

    assert result.success is True
    assert result.source == "springer_oa"
    assert "Springer body" in result.xml_text
    assert "openaccess/jats" in client.calls[1][0]
