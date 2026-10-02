from __future__ import annotations

import json
from pathlib import Path

from multicat.agents.run_agent_cli import run_agent


class DummyClient:
    def __init__(self, response: dict):
        self.response = response

    def chat_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        assert system_prompt
        assert "reaction table" in user_prompt
        return self.response



def test_run_agent_runs_extraction_with_injected_client(tmp_path: Path):
    project_root = tmp_path
    (project_root / "prompts").mkdir()
    (project_root / "prompts" / "extraction_prompt.md").write_text("extraction prompt", encoding="utf-8")
    paper_dir = project_root / "papers" / "P000001"
    paper_dir.mkdir(parents=True)
    (paper_dir / "05_agent_input.md").write_text("reaction table", encoding="utf-8")

    payload = {
        "paper": {},
        "catalysts": [],
        "reactions": [],
        "extraction_meta": {"status": "empty"},
    }
    result = run_agent(
        kind="extraction",
        paper_dir=paper_dir,
        project_root=project_root,
        llm_client=DummyClient(payload),
    )

    assert result == payload
    saved = json.loads((paper_dir / "07_extraction.json").read_text(encoding="utf-8"))
    assert saved["extraction_meta"]["status"] == "empty"


def test_run_agent_runs_judge_with_injected_client(tmp_path: Path):
    project_root = tmp_path
    (project_root / "prompts").mkdir()
    (project_root / "prompts" / "judge_prompt.md").write_text("judge prompt", encoding="utf-8")
    paper_dir = project_root / "papers" / "P000001"
    paper_dir.mkdir(parents=True)
    (paper_dir / "05_agent_input.md").write_text("reaction table", encoding="utf-8")
    (paper_dir / "07_extraction.json").write_text(
        json.dumps({"paper": {}, "catalysts": [], "reactions": [], "extraction_meta": {}}),
        encoding="utf-8",
    )
    (paper_dir / "08_validation.json").write_text(
        json.dumps({"status": "pass", "issues": []}),
        encoding="utf-8",
    )

    result = run_agent(
        kind="judge",
        paper_dir=paper_dir,
        project_root=project_root,
        llm_client=DummyClient({"status": "pass", "issues": [], "summary": "ok"}),
    )

    assert result["status"] == "pass"
    saved = json.loads((paper_dir / "09_judge.json").read_text(encoding="utf-8"))
    assert saved["summary"] == "ok"


def test_run_agent_runs_repair_with_injected_client(tmp_path: Path):
    project_root = tmp_path
    (project_root / "prompts").mkdir()
    (project_root / "prompts" / "repair_prompt.md").write_text("repair prompt", encoding="utf-8")
    paper_dir = project_root / "papers" / "P000001"
    paper_dir.mkdir(parents=True)
    (paper_dir / "05_agent_input.md").write_text("reaction table", encoding="utf-8")
    extraction = {
        "paper": {},
        "catalysts": [],
        "reactions": [],
        "extraction_meta": {"schema_version": "v1"},
    }
    (paper_dir / "07_extraction.json").write_text(json.dumps(extraction), encoding="utf-8")
    (paper_dir / "08_validation.json").write_text(
        json.dumps({"status": "fail", "issues": [{"message": "missing"}]}),
        encoding="utf-8",
    )

    result = run_agent(
        kind="repair",
        paper_dir=paper_dir,
        project_root=project_root,
        llm_client=DummyClient({"repaired_extraction": extraction, "repair_log": []}),
    )

    assert result == extraction
    saved = json.loads((paper_dir / "07_extraction.json").read_text(encoding="utf-8"))
    assert saved == extraction


