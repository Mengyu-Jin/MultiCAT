from multicat.text_acquisition.package_builder import build_text_package_from_xml


def test_build_text_package_from_jats_like_xml_extracts_core_parts():
    xml = """<article>
      <front>
        <article-meta>
          <title-group><article-title>Glucose conversion to lactic acid</article-title></title-group>
          <abstract><p>Sn-Beta converts glucose to lactic acid.</p></abstract>
        </article-meta>
      </front>
      <body>
        <sec><title>Experimental</title><p>Glucose was reacted over Sn-Beta.</p></sec>
        <sec><title>Results and discussion</title><p>Lactic acid yield reached 65%.</p></sec>
        <table-wrap id="t1">
          <caption><title>Reaction results</title></caption>
          <table><tr><th>Catalyst</th><th>Yield</th></tr><tr><td>Sn-Beta</td><td>65%</td></tr></table>
        </table-wrap>
        <fig id="f1"><caption><title>Catalyst characterization</title><p>BET surface area data.</p></caption></fig>
      </body>
    </article>"""

    package = build_text_package_from_xml("P000001", {"doi": "10.0000/example"}, xml)

    assert package["paper_id"] == "P000001"
    assert package["title"] == "Glucose conversion to lactic acid"
    assert "Sn-Beta converts glucose" in package["abstract"]
    assert package["sections"][0]["title"] == "Experimental"
    assert package["tables"][0]["caption"] == "Reaction results"
    assert package["tables"][0]["rows"][1] == ["Sn-Beta", "65%"]
    assert package["figure_captions"][0]["caption"] == "Catalyst characterization BET surface area data."


def test_build_text_package_from_elsevier_xml_extracts_sections_and_tables():
    xml = """<full-text-retrieval-response
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:ce="http://www.elsevier.com/xml/common/dtd"
      xmlns:cals="http://www.elsevier.com/xml/common/cals/dtd">
      <dc:title>Carbonaceous catalyst converts carbohydrates to HMF</dc:title>
      <dc:description>Cellulose-derived catalyst converted glucose to HMF.</dc:description>
      <ce:sections>
        <ce:section>
          <ce:section-title>Results and discussion</ce:section-title>
          <ce:para>Glucose conversion was observed over the carbon catalyst.</ce:para>
        </ce:section>
      </ce:sections>
      <ce:table id="tbl1">
        <ce:label>Table 1</ce:label>
        <ce:caption><ce:simple-para>Reaction performance.</ce:simple-para></ce:caption>
        <cals:tgroup>
          <cals:tbody>
            <cals:row><ce:entry>Substrate</ce:entry><ce:entry>Yield</ce:entry></cals:row>
            <cals:row><ce:entry>Glucose</ce:entry><ce:entry>45%</ce:entry></cals:row>
          </cals:tbody>
        </cals:tgroup>
      </ce:table>
    </full-text-retrieval-response>"""

    package = build_text_package_from_xml("P000003", {"doi": "10.1016/example"}, xml)

    assert package["title"] == "Carbonaceous catalyst converts carbohydrates to HMF"
    assert package["abstract"] == "Cellulose-derived catalyst converted glucose to HMF."
    assert package["sections"][0]["title"] == "Results and discussion"
    assert "Glucose conversion" in package["sections"][0]["text"]
    assert package["tables"][0]["caption"] == "Table 1 Reaction performance."
    assert package["tables"][0]["rows"][1] == ["Glucose", "45%"]
