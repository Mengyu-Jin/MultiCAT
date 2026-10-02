from __future__ import annotations

from pathlib import Path

from multicat.agents.io import read_agent_input, write_agent_json


def run_extraction_agent(paper_dir: Path, llm_client, system_prompt: str) -> dict:
    agent_input = read_agent_input(paper_dir)
    result = llm_client.chat_json(system_prompt=system_prompt, user_prompt=agent_input)
    _validate_extraction_result(result)
    write_agent_json(paper_dir, "07_extraction.json", result)
    return result


def _validate_extraction_result(result: dict) -> None:
    for key in ("paper", "catalysts", "reactions", "extraction_meta"):
        if key not in result:
            raise ValueError(f"Extraction Agent result missing required key: {key}")
    if not isinstance(result["catalysts"], list):
        raise ValueError("Extraction Agent catalysts must be a list.")
    if not isinstance(result["reactions"], list):
        raise ValueError("Extraction Agent reactions must be a list.")
