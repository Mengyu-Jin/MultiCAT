"""Summarize methodology-section statistics for the paper: acceptance
funnel, repair effort, screening exclusion reasons, extraction density,
and LLM cost/runtime -- all derived from files the pipeline already writes
(paper_registry.csv, papers/<id>/06_screening.json, outputs/pipeline_run_report.csv,
outputs/reaction_audit_table_v1.csv, outputs/llm_call_log.jsonl). Pulling these
into one script keeps the reported numbers consistent across batches instead
of being recomputed ad hoc with a different method each time.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from multicat.database_builder.llm_cost_report_cli import load_call_log, summarize

# USD per 1M tokens, OpenRouter list pricing as of 2026-06 (prompt, completion).
# These are publicly listed model prices, not an actual billing export --
# re-check against the OpenRouter dashboard before quoting a final $ figure
# in the dissertation, since list prices can change.
MODEL_PRICING_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "google/gemini-2.5-flash": (0.30, 2.50),
    "anthropic/claude-sonnet-4.5": (3.00, 15.00),
    "openai/gpt-4.1-mini": (0.40, 1.60),
}

SCREENING_EXCLUSION_CATEGORIES: dict[str, tuple[str, ...]] = {
    "fermentation": ("fermentation", "enzymatic", "microbial", "enzyme", "biocatalysis", "yeast", "bacteria"),
    "polyol": ("glycerol", "sorbitol", "xylitol", "polyol", "mannitol"),
    "downstream": (
        "hydrogenation",
        "hydrogenolysis",
        "hydrodeoxygenation",
        "fdca",
        "dmf",
        "gvl",
        "acrylic acid",
        "lactide",
        "biodiesel",
        "transesterification",
    ),
    "other_energy": ("electrocatalysis", "photocatalysis", "battery", "fuel cell"),
    "thermochemical": ("pyrolysis", "gasification", "torrefaction"),
    "review": ("review", "survey"),
    "homogeneous_catalyst": ("homogeneous",),
    "off_target_product": ("not one of the specified target products", "target product"),
}


def load_pipeline_report(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_audit_table(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_screening_decisions(papers_root: Path) -> list[dict[str, Any]]:
    decisions = []
    if not papers_root.exists():
        return decisions
    for paper_dir in sorted(papers_root.iterdir()):
        screening_path = paper_dir / "06_screening.json"
        if not screening_path.exists():
            continue
        try:
            data = json.loads(screening_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        decisions.append(
            {
                "paper_id": paper_dir.name,
                "decision": data.get("decision"),
                "reason": data.get("reason", ""),
            }
        )
    return decisions


def classify_skip_reason(reason: str) -> str:
    reason_lower = reason.lower()
    for category, keywords in SCREENING_EXCLUSION_CATEGORIES.items():
        if any(keyword in reason_lower for keyword in keywords):
            return category
    return "other"


def summarize_screening(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(decisions)
    kept = [d for d in decisions if d.get("decision") == "keep"]
    skipped = [d for d in decisions if d.get("decision") == "skip"]
    skip_reason_counts = Counter(classify_skip_reason(d.get("reason", "")) for d in skipped)
    return {
        "total_screened": total,
        "kept": len(kept),
        "skipped": len(skipped),
        "skip_rate": round(len(skipped) / total, 3) if total else 0,
        "skip_reason_breakdown": dict(skip_reason_counts.most_common()),
    }


def classify_incomplete_reason(notes: str) -> str:
    notes_lower = (notes or "").lower()
    if "screening_skip" in notes_lower:
        return "screening_skip"
    if "watchdog" in notes_lower:
        return "watchdog_timeout"
    if "quota_exhausted" in notes_lower or "quota/auth" in notes_lower:
        return "quota_exhausted"
    if "expecting" in notes_lower or "json" in notes_lower or "delimiter" in notes_lower:
        return "json_parse_error"
    if "reduce reaction count" in notes_lower:
        return "repair_scope_violation"
    if notes_lower.startswith("pipeline_error"):
        return "other_pipeline_error"
    return "unknown"


def summarize_acceptance_funnel(report_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(report_rows)
    status_counts = Counter(r.get("final_status") for r in report_rows)
    incomplete_rows = [r for r in report_rows if r.get("final_status") == "incomplete"]
    incomplete_reason_counts = Counter(classify_incomplete_reason(r.get("notes", "")) for r in incomplete_rows)

    repair_attempts_values = [
        int(r["repair_attempts"]) for r in report_rows if (r.get("repair_attempts") or "").isdigit()
    ]
    first_pass_count = sum(1 for v in repair_attempts_values if v == 0)
    repair_attempts_distribution = Counter(repair_attempts_values)

    return {
        "total_papers": total,
        "final_status_counts": dict(status_counts),
        "acceptance_rate": round(status_counts.get("accepted", 0) / total, 3) if total else 0,
        "rejection_rate": round(status_counts.get("rejected", 0) / total, 3) if total else 0,
        "incomplete_rate": round(status_counts.get("incomplete", 0) / total, 3) if total else 0,
        "incomplete_reason_breakdown": dict(incomplete_reason_counts.most_common()),
        "first_pass_rate_no_repair_needed": round(first_pass_count / len(repair_attempts_values), 3)
        if repair_attempts_values
        else 0,
        "repair_attempts_distribution": dict(sorted(repair_attempts_distribution.items())),
        "avg_repair_attempts": round(statistics.mean(repair_attempts_values), 2)
        if repair_attempts_values
        else 0,
    }


def summarize_extraction_density(audit_rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_paper_counts = Counter(r["paper_id"] for r in audit_rows if r.get("paper_id"))
    counts = list(per_paper_counts.values())
    if not counts:
        return {
            "papers_with_reactions": 0,
            "total_reaction_records": 0,
            "min_reactions_per_paper": 0,
            "max_reactions_per_paper": 0,
            "median_reactions_per_paper": 0,
            "mean_reactions_per_paper": 0,
        }
    return {
        "papers_with_reactions": len(counts),
        "total_reaction_records": sum(counts),
        "min_reactions_per_paper": min(counts),
        "max_reactions_per_paper": max(counts),
        "median_reactions_per_paper": statistics.median(counts),
        "mean_reactions_per_paper": round(statistics.mean(counts), 2),
    }


def estimate_cost_usd(call_log_records: list[dict[str, Any]]) -> dict[str, Any]:
    total_cost = 0.0
    by_model_cost: dict[str, float] = {}
    unpriced_models: set[str] = set()
    for record in call_log_records:
        model = record.get("model", "unknown")
        prompt_tokens = record.get("prompt_tokens") or 0
        completion_tokens = record.get("completion_tokens") or 0
        pricing = MODEL_PRICING_PER_MILLION_TOKENS.get(model)
        if pricing is None:
            unpriced_models.add(model)
            continue
        prompt_price, completion_price = pricing
        cost = (prompt_tokens / 1_000_000) * prompt_price + (completion_tokens / 1_000_000) * completion_price
        total_cost += cost
        by_model_cost[model] = by_model_cost.get(model, 0.0) + cost
    return {
        "total_estimated_cost_usd": round(total_cost, 4),
        "by_model_estimated_cost_usd": {k: round(v, 4) for k, v in by_model_cost.items()},
        "unpriced_models": sorted(unpriced_models),
        "pricing_note": "Estimated from OpenRouter list pricing (USD per 1M tokens), not an actual billing export.",
    }


def build_report(*, papers_root: Path, output_root: Path) -> dict[str, Any]:
    report_rows = load_pipeline_report(output_root / "pipeline_run_report.csv")
    audit_rows = load_audit_table(output_root / "reaction_audit_table_v1.csv")
    screening_decisions = load_screening_decisions(papers_root)
    call_log_records = load_call_log(output_root / "llm_call_log.jsonl")

    return {
        "acceptance_funnel": summarize_acceptance_funnel(report_rows),
        "screening": summarize_screening(screening_decisions),
        "extraction_density": summarize_extraction_density(audit_rows),
        "llm_usage": summarize(call_log_records),
        "estimated_cost": estimate_cost_usd(call_log_records),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize pipeline acceptance/repair/screening/cost statistics for the dissertation methods section."
    )
    parser.add_argument("--papers-root", default="papers")
    parser.add_argument("--output-root", default="outputs")
    args = parser.parse_args()

    report = build_report(papers_root=Path(args.papers_root), output_root=Path(args.output_root))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
