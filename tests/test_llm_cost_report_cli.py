from __future__ import annotations

import json
from pathlib import Path

from multicat.database_builder.llm_cost_report_cli import load_call_log, summarize


def test_load_call_log_returns_empty_list_when_file_missing(tmp_path: Path):
    assert load_call_log(tmp_path / "missing.jsonl") == []


def test_load_call_log_parses_jsonl(tmp_path: Path):
    log_path = tmp_path / "log.jsonl"
    log_path.write_text(
        '{"paper_id": "P000001", "agent_kind": "screening"}\n'
        '{"paper_id": "P000001", "agent_kind": "extraction"}\n',
        encoding="utf-8",
    )

    records = load_call_log(log_path)

    assert len(records) == 2
    assert records[0]["agent_kind"] == "screening"


def test_summarize_aggregates_tokens_duration_and_failures_by_agent_and_model():
    records = [
        {
            "paper_id": "P000001",
            "agent_kind": "screening",
            "model": "google/gemini-2.5-flash",
            "duration_seconds": 2.0,
            "prompt_tokens": 500,
            "completion_tokens": 50,
            "total_tokens": 550,
            "succeeded": True,
        },
        {
            "paper_id": "P000001",
            "agent_kind": "extraction",
            "model": "google/gemini-2.5-flash",
            "duration_seconds": 10.0,
            "prompt_tokens": 2000,
            "completion_tokens": 1500,
            "total_tokens": 3500,
            "succeeded": True,
        },
        {
            "paper_id": "P000002",
            "agent_kind": "extraction",
            "model": "google/gemini-2.5-flash",
            "duration_seconds": 8.0,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "succeeded": False,
            "error": "Unterminated string",
        },
    ]

    summary = summarize(records)

    assert summary["papers_touched"] == 2
    assert summary["total_calls"] == 3
    assert summary["succeeded_calls"] == 2
    assert summary["failed_calls"] == 1
    assert summary["total_prompt_tokens"] == 2500
    assert summary["total_completion_tokens"] == 1550
    assert summary["total_tokens"] == 4050
    assert summary["total_duration_seconds"] == 20.0
    assert summary["avg_duration_seconds_per_call"] == round(20.0 / 3, 2)
    assert summary["by_agent_kind"]["extraction"]["calls"] == 2
    assert summary["by_agent_kind"]["extraction"]["failed"] == 1
    assert summary["by_agent_kind"]["screening"]["calls"] == 1
    assert summary["by_model"]["google/gemini-2.5-flash"]["calls"] == 3
    assert summary["by_model"]["google/gemini-2.5-flash"]["total_tokens"] == 4050


def test_summarize_handles_empty_log():
    summary = summarize([])

    assert summary["total_calls"] == 0
    assert summary["avg_duration_seconds_per_call"] == 0
    assert summary["by_agent_kind"] == {}
