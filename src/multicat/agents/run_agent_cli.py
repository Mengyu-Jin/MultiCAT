from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from threading import Lock

from multicat.agents.extraction_agent import run_extraction_agent
from multicat.agents.judge_agent import run_judge_agent
from multicat.agents.repair_agent import run_repair_agent
from multicat.agents.screening_agent import run_screening_agent
from multicat.llm.model_config import model_for_agent
from multicat.llm.openrouter_client import CallMetrics, OpenRouterClient
from multicat.text_acquisition.env_utils import load_dotenv_keys


PROMPT_FILES = {
    "screening": "screening_prompt.md",
    "extraction": "extraction_prompt.md",
    "judge": "judge_prompt.md",
    "repair": "repair_prompt.md",
}

AGENT_TIMEOUTS = {
    "screening": 90,
    "extraction": 600,
    "judge": 240,
    "repair": 600,
}

_LLM_CALL_LOG_LOCK = Lock()


def run_agent(
    kind: str,
    paper_dir: Path,
    project_root: Path,
    llm_client=None,
    llm_call_log_path: Path | None = None,
) -> dict:
    prompt = _read_prompt(project_root, kind)
    client = llm_client or _build_openrouter_client(
        project_root, kind, paper_dir=paper_dir, llm_call_log_path=llm_call_log_path
    )
    if kind == "screening":
        return run_screening_agent(paper_dir, client, prompt)
    if kind == "extraction":
        return run_extraction_agent(paper_dir, client, prompt)
    if kind == "judge":
        return run_judge_agent(paper_dir, client, prompt)
    if kind == "repair":
        return run_repair_agent(paper_dir, client, prompt)
    raise ValueError(f"Unsupported agent kind: {kind}")


def _read_prompt(project_root: Path, kind: str) -> str:
    try:
        prompt_file = PROMPT_FILES[kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported agent kind: {kind}") from exc
    return (project_root / "prompts" / prompt_file).read_text(encoding="utf-8")


def _build_openrouter_client(
    project_root: Path,
    kind: str,
    *,
    paper_dir: Path,
    llm_call_log_path: Path | None,
) -> OpenRouterClient:
    load_dotenv_keys(project_root)
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")
    log_path = llm_call_log_path or (project_root / "outputs" / "llm_call_log.jsonl")
    return OpenRouterClient(
        api_key=api_key,
        model=model_for_agent(kind),
        timeout=AGENT_TIMEOUTS.get(kind, 180),
        on_call_metrics=lambda metrics: _append_call_log(
            log_path, paper_id=paper_dir.name, agent_kind=kind, metrics=metrics
        ),
    )


def _append_call_log(
    log_path: Path, *, paper_id: str, agent_kind: str, metrics: CallMetrics
) -> None:
    """Append one JSON line per LLM call to outputs/llm_call_log.jsonl.

    This is the raw data source for reporting token usage, call duration,
    and retry counts in the paper's methods/reproducibility section --
    pipeline_run_report.csv only has per-paper summary fields (repair_attempts,
    final_status), not per-call cost/latency.
    """
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "paper_id": paper_id,
        "agent_kind": agent_kind,
        "model": metrics.model,
        "duration_seconds": round(metrics.duration_seconds, 3),
        "prompt_tokens": metrics.prompt_tokens,
        "completion_tokens": metrics.completion_tokens,
        "total_tokens": metrics.total_tokens,
        "attempts": metrics.attempts,
        "succeeded": metrics.succeeded,
        "error": metrics.error,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with _LLM_CALL_LOG_LOCK:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one LLM agent for a paper package.")
    parser.add_argument("--kind", required=True, choices=sorted(PROMPT_FILES))
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--papers-root", default="papers")
    args = parser.parse_args()

    project_root = Path.cwd()
    paper_dir = Path(args.papers_root) / args.paper_id
    result = run_agent(args.kind, paper_dir, project_root)

    if args.kind == "screening":
        print(f"screening_decision={result['decision']} path={paper_dir / '06_screening.json'}")
    elif args.kind == "extraction":
        print(
            "extraction_status=success "
            f"catalysts={len(result['catalysts'])} "
            f"reactions={len(result['reactions'])} "
            f"path={paper_dir / '07_extraction.json'}"
        )
    else:
        if args.kind == "judge":
            print(
                "judge_status="
                f"{result['status']} issues={len(result['issues'])} "
                f"path={paper_dir / '09_judge.json'}"
            )
        else:
            print(
                "repair_status=success "
                f"catalysts={len(result['catalysts'])} "
                f"reactions={len(result['reactions'])} "
                f"path={paper_dir / '07_extraction.json'}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
