from __future__ import annotations

import json
from pathlib import Path

from multicat.ablation.audit_judge import (
    audit_report_is_complete,
    audit_variant_paper,
)


class _AuditRunner:
    def __init__(self):
        self.seen_dir: Path | None = None
        self.validation_calls = 0

    def validate(self, paper_dir: Path) -> dict:
        self.validation_calls += 1
        report = {"status": "pass", "issues": [], "stats": {}}
        (paper_dir / "08_validation.json").write_text(json.dumps(report), encoding="utf-8")
        return report

    def run_agent(self, kind: str, paper_dir: Path, project_root: Path) -> dict:
        assert kind == "judge"
        self.seen_dir = paper_dir
        report = {
            "status": "fail",
            "issues": [
                {"issue_type": "scope_violation", "severity": "error"},
                {"issue_type": "missing_reaction", "severity": "warning"},
            ],
        }
        (paper_dir / "09_judge.json").write_text(json.dumps(report), encoding="utf-8")
        return report


def test_audit_judge_uses_blind_copy_and_does_not_modify_variant(tmp_path: Path):
    variant_dir = tmp_path / "variants" / "no_judge" / "papers" / "P000001"
    variant_dir.mkdir(parents=True)
    original = '{"reactions": [{"reaction_id": "rxn_1"}]}'
    (variant_dir / "07_extraction.json").write_text(original, encoding="utf-8")
    (variant_dir / "05_agent_input.md").write_text("evidence", encoding="utf-8")
    runner = _AuditRunner()

    result = audit_variant_paper(
        variant="no_judge",
        variant_paper_dir=variant_dir,
        output_root=tmp_path,
        project_root=tmp_path,
        runner=runner,
    )

    assert runner.seen_dir == tmp_path / "audit" / "blind" / "P000001"
    assert runner.validation_calls == 1
    assert "no_judge" not in runner.seen_dir.as_posix()
    assert (variant_dir / "07_extraction.json").read_text(encoding="utf-8") == original
    assert not (variant_dir / "09_judge.json").exists()
    assert result.error_counts == {"scope_violation": 1, "missing_reaction": 1}
    assert result.report_path == tmp_path / "audit" / "reports" / "no_judge" / "P000001.json"


def test_audit_report_is_complete_requires_parseable_report_with_status(tmp_path: Path):
    report = tmp_path / "audit" / "reports" / "full" / "P1.json"
    assert audit_report_is_complete(tmp_path, "full", "P1") is False
    report.parent.mkdir(parents=True)
    report.write_text("not-json", encoding="utf-8")
    assert audit_report_is_complete(tmp_path, "full", "P1") is False
    report.write_text(json.dumps({"issues": []}), encoding="utf-8")
    assert audit_report_is_complete(tmp_path, "full", "P1") is False
    report.write_text(json.dumps({"status": "pass", "issues": []}), encoding="utf-8")
    assert audit_report_is_complete(tmp_path, "full", "P1") is True
