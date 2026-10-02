from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_call_log(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    records = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    total_calls = len(records)
    succeeded = [r for r in records if r.get("succeeded")]
    failed = [r for r in records if not r.get("succeeded")]
    total_prompt_tokens = sum(r.get("prompt_tokens") or 0 for r in records)
    total_completion_tokens = sum(r.get("completion_tokens") or 0 for r in records)
    total_tokens = sum(r.get("total_tokens") or 0 for r in records)
    total_duration = sum(r.get("duration_seconds") or 0 for r in records)
    papers = {r.get("paper_id") for r in records if r.get("paper_id")}

    by_agent: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "total_tokens": 0, "total_duration_seconds": 0.0, "failed": 0}
    )
    for r in records:
        bucket = by_agent[r.get("agent_kind", "unknown")]
        bucket["calls"] += 1
        bucket["total_tokens"] += r.get("total_tokens") or 0
        bucket["total_duration_seconds"] += r.get("duration_seconds") or 0
        if not r.get("succeeded"):
            bucket["failed"] += 1

    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "total_tokens": 0}
    )
    for r in records:
        bucket = by_model[r.get("model", "unknown")]
        bucket["calls"] += 1
        bucket["total_tokens"] += r.get("total_tokens") or 0

    return {
        "papers_touched": len(papers),
        "total_calls": total_calls,
        "succeeded_calls": len(succeeded),
        "failed_calls": len(failed),
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "total_duration_seconds": round(total_duration, 1),
        "avg_duration_seconds_per_call": round(total_duration / total_calls, 2)
        if total_calls
        else 0,
        "avg_total_tokens_per_call": round(total_tokens / total_calls, 1) if total_calls else 0,
        "by_agent_kind": dict(by_agent),
        "by_model": dict(by_model),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize outputs/llm_call_log.jsonl for cost/runtime reporting."
    )
    parser.add_argument("--log-path", default="outputs/llm_call_log.jsonl")
    args = parser.parse_args()

    records = load_call_log(Path(args.log_path))
    summary = summarize(records)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
