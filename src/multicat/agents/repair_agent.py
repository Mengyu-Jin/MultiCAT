from __future__ import annotations

import json
from pathlib import Path

from multicat.agents.io import read_agent_input, write_agent_json


def run_repair_agent(paper_dir: Path, llm_client, system_prompt: str) -> dict:
    user_prompt = build_repair_user_prompt(paper_dir)
    original = json.loads((paper_dir / "07_extraction.json").read_text(encoding="utf-8"))
    validation = json.loads((paper_dir / "08_validation.json").read_text(encoding="utf-8"))
    judge = _read_optional_json(paper_dir / "09_judge.json")
    result = llm_client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
    repaired = _extract_repaired_payload(result)
    _validate_repair_scope(original, repaired, validation, judge)
    repair_log = result.get("repair_log", [])
    if not isinstance(repair_log, list):
        raise ValueError("Repair Agent repair_log must be a list.")
    write_agent_json(paper_dir, "07_extraction.json", repaired)
    write_agent_json(paper_dir, "10_repair_log.json", repair_log)
    return repaired


def build_repair_user_prompt(paper_dir: Path) -> str:
    agent_input = read_agent_input(paper_dir)
    extraction = json.loads((paper_dir / "07_extraction.json").read_text(encoding="utf-8"))
    validation = json.loads((paper_dir / "08_validation.json").read_text(encoding="utf-8"))
    parts = [
        "## Agent Input",
        agent_input,
        "## Extraction JSON",
        json.dumps(extraction, ensure_ascii=False, indent=2),
        "## Validation Report",
        json.dumps(validation, ensure_ascii=False, indent=2),
    ]
    judge_path = paper_dir / "09_judge.json"
    if judge_path.exists():
        judge = json.loads(judge_path.read_text(encoding="utf-8"))
        parts.extend(["## Judge Report", json.dumps(judge, ensure_ascii=False, indent=2)])
    return "\n\n".join(parts)


def _extract_repaired_payload(result: dict) -> dict:
    repaired = result.get("repaired_extraction", result.get("extraction"))
    if not isinstance(repaired, dict):
        raise ValueError("Repair Agent result must contain repaired_extraction object.")
    for key in ("paper", "catalysts", "reactions", "extraction_meta"):
        if key not in repaired:
            raise ValueError(f"Repair Agent repaired_extraction missing {key}.")
    return repaired


def _read_optional_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_repair_scope(
    original: dict,
    repaired: dict,
    validation: dict,
    judge: dict | None,
) -> None:
    original_count = len(original.get("reactions", []))
    repaired_count = len(repaired.get("reactions", []))
    if repaired_count >= original_count:
        return
    issue_text = json.dumps(validation.get("issues", []), ensure_ascii=False).lower()
    if judge:
        issue_text += json.dumps(judge.get("issues", []), ensure_ascii=False).lower()
    deletion_allowed_terms = (
        "homogeneous",
        "out of scope",
        "no-catalyst",
        "no catalyst",
        "duplicate",
        "merged",
        "remove",
        "delete",
    )
    if not any(term in issue_text for term in deletion_allowed_terms):
        raise ValueError(
            "Repair must not reduce reaction count when issues only require additions or fixes."
        )
