from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class AuditRunner(Protocol):
    def validate(self, paper_dir: Path) -> dict: ...

    def run_agent(self, kind: str, paper_dir: Path, project_root: Path) -> dict: ...


@dataclass(frozen=True)
class AuditResult:
    variant: str
    paper_id: str
    status: str
    error_counts: dict[str, int]
    report_path: Path


def audit_report_is_complete(output_root: Path, variant: str, paper_id: str) -> bool:
    report_path = output_root / "audit" / "reports" / variant / f"{paper_id}.json"
    if not report_path.exists():
        return False
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return report.get("status") in {"pass", "fail"} and isinstance(
        report.get("issues"), list
    )


def audit_variant_paper(
    *,
    variant: str,
    variant_paper_dir: Path,
    output_root: Path,
    project_root: Path,
    runner: AuditRunner,
) -> AuditResult:
    """Evaluate one variant in a blind temporary workspace without mutation."""
    paper_id = variant_paper_dir.name
    blind_dir = output_root / "audit" / "blind" / paper_id
    if blind_dir.exists():
        shutil.rmtree(blind_dir)
    blind_dir.mkdir(parents=True)
    for filename in ("05_agent_input.md", "07_extraction.json"):
        source = variant_paper_dir / filename
        if source.exists():
            shutil.copy2(source, blind_dir / filename)

    runner.validate(blind_dir)
    report = runner.run_agent("judge", blind_dir, project_root)
    error_counts: dict[str, int] = {}
    for issue in report.get("issues") or []:
        issue_type = issue.get("issue_type") or issue.get("type") or "other"
        error_counts[issue_type] = error_counts.get(issue_type, 0) + 1

    report_path = output_root / "audit" / "reports" / variant / f"{paper_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(blind_dir)
    return AuditResult(
        variant=variant,
        paper_id=paper_id,
        status=report.get("status", "unknown"),
        error_counts=error_counts,
        report_path=report_path,
    )
