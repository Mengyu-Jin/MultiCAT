from __future__ import annotations

import csv
import json
from pathlib import Path

from multicat.database_builder.pipeline_stats_report_cli import (
    build_report,
    classify_incomplete_reason,
    classify_skip_reason,
    estimate_cost_usd,
    summarize_acceptance_funnel,
    summarize_extraction_density,
    summarize_screening,
)


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_classify_skip_reason_matches_known_exclusion_categories():
    assert classify_skip_reason("This is a fermentation/enzymatic process.") == "fermentation"
    assert classify_skip_reason("Uses glycerol as feedstock.") == "polyol"
    assert classify_skip_reason("This is a flash pyrolysis study.") == "thermochemical"
    assert classify_skip_reason("A review of recent advances.") == "review"
    assert classify_skip_reason("Some unrelated reason text.") == "other"


def test_classify_incomplete_reason_distinguishes_known_failure_modes():
    assert classify_incomplete_reason("screening_skip") == "screening_skip"
    assert classify_incomplete_reason("pipeline_error: exceeded 900s watchdog timeout") == "watchdog_timeout"
    assert (
        classify_incomplete_reason("pipeline_error: skipped, API quota/auth already exhausted in this batch")
        == "quota_exhausted"
    )
    assert (
        classify_incomplete_reason("pipeline_error: Expecting value: line 2 column 11 (char 12)")
        == "json_parse_error"
    )
    assert (
        classify_incomplete_reason(
            "pipeline_error: Repair must not reduce reaction count when issues only require additions or fixes."
        )
        == "repair_scope_violation"
    )


def test_summarize_acceptance_funnel_computes_rates_and_repair_distribution():
    rows = [
        {"final_status": "accepted", "repair_attempts": "0", "notes": ""},
        {"final_status": "accepted", "repair_attempts": "1", "notes": ""},
        {"final_status": "rejected", "repair_attempts": "2", "notes": "some issue"},
        {"final_status": "incomplete", "repair_attempts": "0", "notes": "screening_skip"},
    ]

    summary = summarize_acceptance_funnel(rows)

    assert summary["total_papers"] == 4
    assert summary["final_status_counts"] == {"accepted": 2, "rejected": 1, "incomplete": 1}
    assert summary["acceptance_rate"] == 0.5
    assert summary["rejection_rate"] == 0.25
    assert summary["incomplete_rate"] == 0.25
    assert summary["incomplete_reason_breakdown"] == {"screening_skip": 1}
    assert summary["first_pass_rate_no_repair_needed"] == 0.5
    assert summary["repair_attempts_distribution"] == {0: 2, 1: 1, 2: 1}


def test_summarize_screening_computes_skip_rate_and_reason_breakdown():
    decisions = [
        {"paper_id": "P000001", "decision": "keep", "reason": ""},
        {"paper_id": "P000002", "decision": "skip", "reason": "This involves fermentation."},
        {"paper_id": "P000003", "decision": "skip", "reason": "Uses glycerol feedstock."},
    ]

    summary = summarize_screening(decisions)

    assert summary["total_screened"] == 3
    assert summary["kept"] == 1
    assert summary["skipped"] == 2
    assert summary["skip_rate"] == round(2 / 3, 3)
    assert summary["skip_reason_breakdown"] == {"fermentation": 1, "polyol": 1}


def test_summarize_extraction_density_computes_per_paper_distribution():
    rows = [
        {"paper_id": "P000001"},
        {"paper_id": "P000001"},
        {"paper_id": "P000001"},
        {"paper_id": "P000002"},
    ]

    summary = summarize_extraction_density(rows)

    assert summary["papers_with_reactions"] == 2
    assert summary["total_reaction_records"] == 4
    assert summary["min_reactions_per_paper"] == 1
    assert summary["max_reactions_per_paper"] == 3
    assert summary["median_reactions_per_paper"] == 2


def test_estimate_cost_usd_uses_known_model_pricing_and_flags_unknown_models():
    records = [
        {"model": "google/gemini-2.5-flash", "prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
        {"model": "some/unknown-model", "prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
    ]

    summary = estimate_cost_usd(records)

    # gemini-2.5-flash: 0.30 (prompt) + 2.50 (completion) per 1M tokens
    assert summary["total_estimated_cost_usd"] == 2.80
    assert summary["by_model_estimated_cost_usd"] == {"google/gemini-2.5-flash": 2.80}
    assert summary["unpriced_models"] == ["some/unknown-model"]


def test_build_report_merges_all_data_sources(tmp_path: Path):
    papers_root = tmp_path / "papers"
    output_root = tmp_path / "outputs"

    paper_dir = papers_root / "P000001"
    paper_dir.mkdir(parents=True)
    (paper_dir / "06_screening.json").write_text(
        json.dumps({"decision": "keep", "reason": ""}), encoding="utf-8"
    )

    skip_dir = papers_root / "P000002"
    skip_dir.mkdir(parents=True)
    (skip_dir / "06_screening.json").write_text(
        json.dumps({"decision": "skip", "reason": "This involves fermentation."}), encoding="utf-8"
    )

    _write_csv(
        output_root / "pipeline_run_report.csv",
        ["paper_id", "final_status", "repair_attempts", "notes"],
        [
            {"paper_id": "P000001", "final_status": "accepted", "repair_attempts": "0", "notes": ""},
            {"paper_id": "P000002", "final_status": "incomplete", "repair_attempts": "0", "notes": "screening_skip"},
        ],
    )
    _write_csv(
        output_root / "reaction_audit_table_v1.csv",
        ["paper_id", "reaction_id"],
        [{"paper_id": "P000001", "reaction_id": "rxn_001"}],
    )
    (output_root / "llm_call_log.jsonl").write_text(
        json.dumps(
            {
                "agent_kind": "screening",
                "model": "google/gemini-2.5-flash",
                "duration_seconds": 1.0,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "succeeded": True,
                "paper_id": "P000001",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_report(papers_root=papers_root, output_root=output_root)

    assert report["acceptance_funnel"]["total_papers"] == 2
    assert report["screening"]["skipped"] == 1
    assert report["extraction_density"]["total_reaction_records"] == 1
    assert report["llm_usage"]["total_calls"] == 1
    assert report["estimated_cost"]["total_estimated_cost_usd"] > 0
