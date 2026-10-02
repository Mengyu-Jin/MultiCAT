from __future__ import annotations

import json
from pathlib import Path


def read_agent_input(paper_dir: Path) -> str:
    input_path = paper_dir / "05_agent_input.md"
    if not input_path.exists():
        raise FileNotFoundError(f"Missing agent input: {input_path}")
    return input_path.read_text(encoding="utf-8")


def write_agent_json(paper_dir: Path, filename: str, payload: dict) -> Path:
    output_path = paper_dir / filename
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path

