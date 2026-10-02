import json

from multicat.agents.extraction_agent import run_extraction_agent
from multicat.agents.judge_agent import run_judge_agent
from multicat.agents.repair_agent import run_repair_agent
from multicat.agents.screening_agent import run_screening_agent


class FakeLlmClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat_json(self, *, system_prompt, user_prompt):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if not self.responses:
            raise AssertionError("No fake LLM response configured")
        return self.responses.pop(0)


def test_run_screening_agent_reads_agent_input_and_writes_screening_json(tmp_path):
    (tmp_path / "05_agent_input.md").write_text(
        "# Agent Input\nGlucose was converted to HMF over Nb-Al catalyst.",
        encoding="utf-8",
    )
    client = FakeLlmClient([{"decision": "keep", "reason": "Reports glucose to HMF yield."}])

    result = run_screening_agent(tmp_path, client, "Screening rules")

    assert result["decision"] == "keep"
    output = json.loads((tmp_path / "06_screening.json").read_text(encoding="utf-8"))
    assert output == result
    assert "Glucose was converted" in client.calls[0]["user_prompt"]
    assert client.calls[0]["system_prompt"] == "Screening rules"



def test_run_screening_agent_overrides_dissolved_alcl3_keep_to_skip(tmp_path):
    (tmp_path / "05_agent_input.md").write_text(
        "# Agent Input\n"
        "Glucose was converted to HMF using AlCl3·6H2O dissolved in phosphate buffer.",
        encoding="utf-8",
    )
    client = FakeLlmClient(
        [
            {
                "decision": "keep",
                "reason": "The catalyst is a solid salt dissolved in aqueous phase.",
            }
        ]
    )

    result = run_screening_agent(tmp_path, client, "Screening rules")

    assert result["decision"] == "skip"
    assert "deterministic override" in result["reason"]
    output = json.loads((tmp_path / "06_screening.json").read_text(encoding="utf-8"))
    assert output == result


def test_run_extraction_agent_writes_extraction_json(tmp_path):
    (tmp_path / "05_agent_input.md").write_text(
        "# Agent Input\nGlucose conversion was 90% and HMF yield was 59%.",
        encoding="utf-8",
    )
    extraction = {
        "paper": {"paper_id": "P000001", "doi": "10.0000/example"},
        "catalysts": [{"catalyst_id": "cat_1", "catalyst_name": "Nb-Al"}],
        "reactions": [
            {
                "reaction_id": None,
                "paper_id": "P000001",
                "catalyst_id": "cat_1",
                "substrate_name": "glucose",
                "products": [
                    {
                        "product_name": "HMF",
                        "yield": {"value": 59, "unit": "%", "original_label": "HMF yield"},
                    }
                ],
                "evidence": "HMF yield was 59%.",
            }
        ],
        "extraction_meta": {"model": "fake"},
    }
    client = FakeLlmClient([extraction])

    result = run_extraction_agent(tmp_path, client, "Extraction rules")

    assert result == extraction
    output = json.loads((tmp_path / "07_extraction.json").read_text(encoding="utf-8"))
    assert output == extraction
    assert "HMF yield was 59%" in client.calls[0]["user_prompt"]


def test_run_judge_agent_reads_source_extraction_and_validation_then_writes_judge_json(tmp_path):
    (tmp_path / "05_agent_input.md").write_text(
        "# Agent Input\nTable 1 reports glucose conversion and HMF yield.",
        encoding="utf-8",
    )
    (tmp_path / "07_extraction.json").write_text(
        json.dumps(
            {
                "paper": {"paper_id": "P000001"},
                "catalysts": [{"catalyst_id": "cat_1"}],
                "reactions": [{"reaction_id": "rxn_1", "catalyst_id": "cat_1"}],
                "extraction_meta": {},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "08_validation.json").write_text(
        json.dumps({"status": "pass", "issues": []}),
        encoding="utf-8",
    )
    judge = {
        "status": "pass",
        "issues": [],
        "summary": "Extraction is consistent with the visible table.",
    }
    client = FakeLlmClient([judge])

    result = run_judge_agent(tmp_path, client, "Judge rules")

    assert result == judge
    output = json.loads((tmp_path / "09_judge.json").read_text(encoding="utf-8"))
    assert output == judge
    user_prompt = client.calls[0]["user_prompt"]
    assert "## Agent Input" in user_prompt
    assert "## Extraction JSON" in user_prompt
    assert "## Validation Report" in user_prompt


def test_run_judge_agent_normalizes_decision_to_status(tmp_path):
    (tmp_path / "05_agent_input.md").write_text("source text", encoding="utf-8")
    (tmp_path / "07_extraction.json").write_text(
        json.dumps({"paper": {}, "catalysts": [], "reactions": [], "extraction_meta": {}}),
        encoding="utf-8",
    )
    (tmp_path / "08_validation.json").write_text(
        json.dumps({"status": "pass", "issues": []}),
        encoding="utf-8",
    )
    client = FakeLlmClient(
        [
            {
                "decision": "fail",
                "issue_list": [{"type": "missing_table_row", "message": "One table row is missing."}],
            }
        ]
    )

    result = run_judge_agent(tmp_path, client, "Judge rules")

    assert result == {
        "status": "fail",
        "issues": [{"type": "missing_table_row", "message": "One table row is missing."}],
        "summary": None,
    }


def test_run_repair_agent_reads_validation_and_writes_repaired_extraction(tmp_path):
    (tmp_path / "05_agent_input.md").write_text(
        "# Agent Input\nTable 1 has one missing heterogeneous catalyst row.",
        encoding="utf-8",
    )
    original = {
        "paper": {"paper_id": "P000003"},
        "catalysts": [{"catalyst_id": "cat_001", "catalyst_name": "CCC"}],
        "reactions": [],
        "extraction_meta": {"schema_version": "v1", "status": "complete", "notes": None},
    }
    repaired = {
        **original,
        "reactions": [{"reaction_id": "rxn_001", "catalyst_id": "cat_001"}],
    }
    (tmp_path / "07_extraction.json").write_text(
        json.dumps(original),
        encoding="utf-8",
    )
    (tmp_path / "08_validation.json").write_text(
        json.dumps({"status": "fail", "issues": [{"message": "missing row"}]}),
        encoding="utf-8",
    )
    (tmp_path / "09_judge.json").write_text(
        json.dumps({"status": "fail", "issues": [{"message": "missing row"}]}),
        encoding="utf-8",
    )
    client = FakeLlmClient(
        [
            {
                "repaired_extraction": repaired,
                "repair_log": [{"action": "added missing row"}],
            }
        ]
    )

    result = run_repair_agent(tmp_path, client, "Repair rules")

    assert result == repaired
    saved = json.loads((tmp_path / "07_extraction.json").read_text(encoding="utf-8"))
    assert saved == repaired
    repair_log = json.loads((tmp_path / "10_repair_log.json").read_text(encoding="utf-8"))
    assert repair_log == [{"action": "added missing row"}]
    user_prompt = client.calls[0]["user_prompt"]
    assert "## Agent Input" in user_prompt
    assert "## Extraction JSON" in user_prompt
    assert "## Validation Report" in user_prompt
    assert "## Judge Report" in user_prompt


def test_run_repair_agent_rejects_reaction_decrease_for_missing_only_issues(tmp_path):
    (tmp_path / "05_agent_input.md").write_text("source", encoding="utf-8")
    original = {
        "paper": {},
        "catalysts": [],
        "reactions": [{"reaction_id": "rxn_001"}, {"reaction_id": "rxn_002"}],
        "extraction_meta": {},
    }
    repaired = {**original, "reactions": [{"reaction_id": "rxn_001"}]}
    (tmp_path / "07_extraction.json").write_text(json.dumps(original), encoding="utf-8")
    (tmp_path / "08_validation.json").write_text(
        json.dumps(
            {
                "status": "fail",
                "issues": [
                    {
                        "message": "Valid heterogeneous catalyst table row is missing from extraction."
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    client = FakeLlmClient([{"repaired_extraction": repaired, "repair_log": []}])

    try:
        run_repair_agent(tmp_path, client, "Repair rules")
    except ValueError as exc:
        assert "must not reduce reaction count" in str(exc)
    else:
        raise AssertionError("Expected repair count guard to reject over-deletion")
