from __future__ import annotations

import json
from pathlib import Path

from multicat.agents.io import read_agent_input, write_agent_json


def run_judge_agent(paper_dir: Path, llm_client, system_prompt: str) -> dict:
    user_prompt = build_judge_user_prompt(paper_dir)
    result = _normalize_judge_result(
        llm_client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
    )
    _validate_judge_result(result)
    write_agent_json(paper_dir, "09_judge.json", result)
    return result


def build_judge_user_prompt(paper_dir: Path) -> str:
    agent_input = read_agent_input(paper_dir)
    extraction = json.loads((paper_dir / "07_extraction.json").read_text(encoding="utf-8"))
    validation = json.loads((paper_dir / "08_validation.json").read_text(encoding="utf-8"))
    parts = [
        "## Agent Input",
        agent_input,
        "## Extraction JSON (source_type=text)",
        json.dumps(extraction, ensure_ascii=False, indent=2),
        "## Validation Report",
        json.dumps(validation, ensure_ascii=False, indent=2),
    ]
    return "\n\n".join(parts)


def _normalize_judge_result(result: dict) -> dict:
    return {
        "status": result.get("status", result.get("decision")),
        "issues": result.get("issues", result.get("issue_list", [])),
        "summary": result.get("summary"),
    }


def _validate_judge_result(result: dict) -> None:
    if result.get("status") not in {"pass", "fail"}:
        raise ValueError("Judge Agent result must contain status=pass or fail.")
    if not isinstance(result.get("issues"), list):
        raise ValueError("Judge Agent issues must be a list.")
