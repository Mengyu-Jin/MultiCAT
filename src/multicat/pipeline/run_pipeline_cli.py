from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Protocol

from multicat.agents.run_agent_cli import run_agent
from multicat.database_builder.reaction_table_builder_v1 import write_v1_tables
from multicat.llm.model_config import model_for_agent
from multicat.llm.openrouter_client import QuotaExhaustedError
from multicat.text_acquisition.agent_input_builder import build_agent_input_markdown
from multicat.validator.extraction_validator import validate_extraction_file


# Issue types that Repair cannot fix: the underlying fact in the paper has not
# changed (e.g. a homogeneous catalyst really is homogeneous; a scope violation
# means the paper was wrongly included, not that the extraction is fixable).
_UNRECOVERABLE_JUDGE_ISSUE_TYPES: frozenset[str] = frozenset(
    {"out_of_scope_catalyst", "scope_violation"}
)


def _judge_issues_are_all_unrecoverable(judge: dict) -> bool:
    issues = judge.get("issues") or []
    if not issues:
        return False
    return all(
        issue.get("type") in _UNRECOVERABLE_JUDGE_ISSUE_TYPES for issue in issues
    )


def _log_progress(paper_id: str, message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {paper_id}: {message}", file=sys.stderr, flush=True)


class PipelineRunner(Protocol):
    def run_agent(self, kind: str, paper_dir: Path, project_root: Path) -> dict: ...

    def validate(self, paper_dir: Path) -> dict: ...


@dataclass
class DefaultPipelineRunner:
    output_root: Path = field(default_factory=lambda: Path("outputs"))

    def run_agent(self, kind: str, paper_dir: Path, project_root: Path) -> dict:
        return run_agent(
            kind=kind,
            paper_dir=paper_dir,
            project_root=project_root,
            llm_call_log_path=self.output_root / "llm_call_log.jsonl",
        )

    def validate(self, paper_dir: Path) -> dict:
        return validate_extraction_file(paper_dir)


@dataclass
class PaperPipelineResult:
    paper_id: str
    final_status: str
    validation_status: str | None = None
    judge_status: str | None = None
    validation_repair_attempts: int = 0
    judge_repair_attempts: int = 0
    extraction_model: str = ""
    judge_model: str = ""
    repair_model: str = ""
    notes: str = ""


@dataclass
class PipelineResult:
    paper_results: list[PaperPipelineResult] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)
    audit_table: Path | None = None
    ml_ready_table: Path | None = None


def run_pipeline(
    *,
    project_root: Path,
    papers_root: Path,
    output_root: Path,
    paper_ids: list[str] | None = None,
    max_repair_loops: int = 2,
    skip_existing_pass: bool = False,
    extraction_mode: str = "full",
    runner: PipelineRunner | None = None,
    workers: int = 4,
    paper_timeout_seconds: float = 3600,
) -> PipelineResult:
    runner = runner or DefaultPipelineRunner(output_root=output_root)
    selected_paper_ids = paper_ids or _discover_paper_ids(papers_root)
    result = PipelineResult()

    paper_started_at: dict[str, float] = {}
    paper_started_lock = Lock()
    quota_exhausted = Event()

    def _run(paper_id: str) -> PaperPipelineResult:
        if quota_exhausted.is_set():
            # Another paper already hit an unrecoverable account/billing
            # failure. Don't burn time retrying every remaining paper in an
            # unattended batch -- short-circuit immediately.
            return PaperPipelineResult(
                paper_id=paper_id,
                final_status="incomplete",
                extraction_model=model_for_agent("extraction"),
                judge_model=model_for_agent("judge"),
                repair_model=model_for_agent("repair"),
                notes="pipeline_error: skipped, API quota/auth already exhausted in this batch",
            )
        with paper_started_lock:
            paper_started_at[paper_id] = time.monotonic()
        try:
            return _run_one_paper(
                paper_id=paper_id,
                paper_dir=papers_root / paper_id,
                project_root=project_root,
                max_repair_loops=max_repair_loops,
                skip_existing_pass=skip_existing_pass,
                extraction_mode=extraction_mode,
                runner=runner,
            )
        except QuotaExhaustedError as exc:
            quota_exhausted.set()
            _log_progress(paper_id, f"quota_exhausted: stopping batch -> {exc}")
            return PaperPipelineResult(
                paper_id=paper_id,
                final_status="incomplete",
                extraction_model=model_for_agent("extraction"),
                judge_model=model_for_agent("judge"),
                repair_model=model_for_agent("repair"),
                notes=f"pipeline_error: quota_exhausted: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - isolate one paper's failure from the batch
            return PaperPipelineResult(
                paper_id=paper_id,
                final_status="incomplete",
                extraction_model=model_for_agent("extraction"),
                judge_model=model_for_agent("judge"),
                repair_model=model_for_agent("repair"),
                notes=f"pipeline_error: {exc}",
            )

    # Use cancel_futures=True so that when watchdog abandons a timed-out
    # future the executor does not block forever waiting for it on __exit__.
    # Worker threads for timed-out papers are daemons (via openrouter_client's
    # daemon Thread), so they won't prevent process exit.
    executor = ThreadPoolExecutor(max_workers=workers)
    futures = {executor.submit(_run, pid): pid for pid in selected_paper_ids}
    paper_results: dict[str, PaperPipelineResult] = {}
    pending = set(futures)
    try:
        while pending:
            poll_interval = min(5.0, max(0.05, paper_timeout_seconds / 4))
            done, pending = wait(pending, timeout=poll_interval, return_when=FIRST_COMPLETED)
            for future in done:
                paper_id = futures[future]
                paper_results[paper_id] = future.result()
            timed_out = set()
            for future in pending:
                paper_id = futures[future]
                with paper_started_lock:
                    started = paper_started_at.get(paper_id)
                if started is not None and time.monotonic() - started > paper_timeout_seconds:
                    timed_out.add(future)
            for future in timed_out:
                paper_id = futures[future]
                _log_progress(
                    paper_id,
                    f"watchdog: exceeded {paper_timeout_seconds}s -> incomplete (worker thread abandoned)",
                )
                paper_results[paper_id] = PaperPipelineResult(
                    paper_id=paper_id,
                    final_status="incomplete",
                    extraction_model=model_for_agent("extraction"),
                    judge_model=model_for_agent("judge"),
                    repair_model=model_for_agent("repair"),
                    notes=f"pipeline_error: exceeded {paper_timeout_seconds}s watchdog timeout",
                )
                future.cancel()
                pending.discard(future)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    for paper_id in selected_paper_ids:
        paper_result = paper_results[paper_id]
        result.paper_results.append(paper_result)
        if paper_result.final_status == "accepted":
            result.accepted.append(paper_id)
        elif paper_result.final_status == "rejected":
            result.rejected.append(paper_id)
        else:
            result.incomplete.append(paper_id)

    try:
        result.audit_table, result.ml_ready_table = write_v1_tables(papers_root, output_root)
    except OSError as exc:
        # Every paper has already finished and its status is durably saved
        # under papers/<id>/08_validation.json and 09_judge.json. A transient
        # file-lock failure on the summary CSV (e.g. it's open in Excel) must
        # not throw away an entire overnight batch's results.
        _log_progress("batch", f"failed to write database tables: {exc}")
    try:
        _write_pipeline_reports(result, output_root)
    except OSError as exc:
        _log_progress("batch", f"failed to write pipeline reports: {exc}")
    return result


def _run_one_paper(
    *,
    paper_id: str,
    paper_dir: Path,
    project_root: Path,
    max_repair_loops: int,
    skip_existing_pass: bool,
    extraction_mode: str,
    runner: PipelineRunner,
) -> PaperPipelineResult:
    if not paper_dir.exists():
        return PaperPipelineResult(
            paper_id=paper_id,
            final_status="incomplete",
            extraction_model=model_for_agent("extraction"),
            judge_model=model_for_agent("judge"),
            repair_model=model_for_agent("repair"),
            notes="paper directory missing",
        )
    _prepare_agent_input(paper_dir, extraction_mode)
    if not (paper_dir / "05_agent_input.md").exists():
        return PaperPipelineResult(
            paper_id=paper_id,
            final_status="incomplete",
            extraction_model=model_for_agent("extraction"),
            judge_model=model_for_agent("judge"),
            repair_model=model_for_agent("repair"),
            notes="05_agent_input.md missing",
        )
    if skip_existing_pass and _has_existing_pass(paper_dir):
        return PaperPipelineResult(
            paper_id=paper_id,
            final_status="accepted",
            validation_status="pass",
            judge_status="pass",
            extraction_model=model_for_agent("extraction"),
            judge_model=model_for_agent("judge"),
            repair_model=model_for_agent("repair"),
            notes="skipped existing pass",
        )
    if skip_existing_pass and _has_existing_rejected(paper_dir):
        return PaperPipelineResult(
            paper_id=paper_id,
            final_status="rejected",
            extraction_model=model_for_agent("extraction"),
            judge_model=model_for_agent("judge"),
            repair_model=model_for_agent("repair"),
            notes="skipped existing rejected",
        )
    if skip_existing_pass and _screening_is_skip(paper_dir):
        return PaperPipelineResult(
            paper_id=paper_id,
            final_status="incomplete",
            extraction_model=model_for_agent("extraction"),
            judge_model=model_for_agent("judge"),
            repair_model=model_for_agent("repair"),
            notes="skipped existing screening_skip",
        )
    if skip_existing_pass and _has_extraction_but_no_judge(paper_dir):
        # Extraction completed but pipeline hung before judge — likely a
        # drip-slow LLM hang. Skip to avoid infinite retry of broken papers.
        return PaperPipelineResult(
            paper_id=paper_id,
            final_status="incomplete",
            extraction_model=model_for_agent("extraction"),
            judge_model=model_for_agent("judge"),
            repair_model=model_for_agent("repair"),
            notes="skipped pipeline_error: extraction exists but no judge (likely prior hang)",
        )

    _screening_cache = paper_dir / "06_screening.json"
    if _screening_cache.exists():
        import json as _json
        try:
            _cached = _json.loads(_screening_cache.read_text(encoding="utf-8"))
            if _cached.get("decision") == "keep":
                _log_progress(paper_id, "screening: cached keep, skipping LLM call")
            else:
                _log_progress(paper_id, "screening: starting (cache exists but not keep)")
                runner.run_agent("screening", paper_dir, project_root)
                _log_progress(paper_id, "screening: done")
        except Exception:
            _log_progress(paper_id, "screening: starting (cache parse failed)")
            runner.run_agent("screening", paper_dir, project_root)
            _log_progress(paper_id, "screening: done")
    else:
        _log_progress(paper_id, "screening: starting")
        runner.run_agent("screening", paper_dir, project_root)
        _log_progress(paper_id, "screening: done")

    if _screening_is_skip(paper_dir):
        _log_progress(paper_id, "screening_skip -> incomplete")
        return PaperPipelineResult(
            paper_id=paper_id,
            final_status="incomplete",
            extraction_model=model_for_agent("extraction"),
            judge_model=model_for_agent("judge"),
            repair_model=model_for_agent("repair"),
            notes="screening_skip",
        )

    _log_progress(paper_id, "extraction: starting")
    runner.run_agent("extraction", paper_dir, project_root)
    _log_progress(paper_id, "extraction: done")

    # --- Validate + repair (independent counter) ---
    validation_repair_attempts = 0
    validation = runner.validate(paper_dir)
    _log_progress(paper_id, f"validate: status={validation.get('status')}")
    while validation.get("status") != "pass" and validation_repair_attempts < max_repair_loops:
        _log_progress(paper_id, f"repair: attempt {validation_repair_attempts + 1}/{max_repair_loops} (validation)")
        try:
            runner.run_agent("repair", paper_dir, project_root)
        except ValueError as exc:
            _log_progress(paper_id, f"repair: rejected repair output ({exc}); retrying without applying it")
        validation_repair_attempts += 1
        validation = runner.validate(paper_dir)
        _log_progress(paper_id, f"validate: status={validation.get('status')}")

    if validation.get("status") != "pass":
        _log_progress(paper_id, "validation failed after repairs -> rejected")
        return PaperPipelineResult(
            paper_id=paper_id,
            final_status="rejected",
            validation_status=validation.get("status"),
            validation_repair_attempts=validation_repair_attempts,
            extraction_model=model_for_agent("extraction"),
            judge_model=model_for_agent("judge"),
            repair_model=model_for_agent("repair"),
            notes=_issue_summary(validation),
        )

    # --- Judge + repair (independent counter) ---
    _log_progress(paper_id, "judge: starting")
    judge = runner.run_agent("judge", paper_dir, project_root)
    _log_progress(paper_id, f"judge: status={judge.get('status')}")
    if judge.get("status") != "pass" and _judge_issues_are_all_unrecoverable(judge):
        _log_progress(paper_id, "judge: unrecoverable issues, skipping repair -> rejected")
        return PaperPipelineResult(
            paper_id=paper_id,
            final_status="rejected",
            validation_status=validation.get("status"),
            judge_status=judge.get("status"),
            validation_repair_attempts=validation_repair_attempts,
            extraction_model=model_for_agent("extraction"),
            judge_model=model_for_agent("judge"),
            repair_model=model_for_agent("repair"),
            notes=_issue_summary(judge),
        )
    judge_repair_attempts = 0
    while judge.get("status") != "pass" and judge_repair_attempts < max_repair_loops:
        _log_progress(paper_id, f"repair: attempt {judge_repair_attempts + 1}/{max_repair_loops} (judge)")
        try:
            runner.run_agent("repair", paper_dir, project_root)
        except ValueError as exc:
            _log_progress(paper_id, f"repair: rejected repair output ({exc}); retrying without applying it")
        judge_repair_attempts += 1
        validation = runner.validate(paper_dir)
        _log_progress(paper_id, f"validate: status={validation.get('status')}")
        if validation.get("status") != "pass":
            continue
        judge = runner.run_agent("judge", paper_dir, project_root)
        _log_progress(paper_id, f"judge: status={judge.get('status')}")

    final_status = "accepted" if validation.get("status") == "pass" and judge.get("status") == "pass" else "rejected"
    _log_progress(paper_id, f"final_status={final_status}")
    return PaperPipelineResult(
        paper_id=paper_id,
        final_status=final_status,
        validation_status=validation.get("status"),
        judge_status=judge.get("status"),
        validation_repair_attempts=validation_repair_attempts,
        judge_repair_attempts=judge_repair_attempts,
        extraction_model=model_for_agent("extraction"),
        judge_model=model_for_agent("judge"),
        repair_model=model_for_agent("repair"),
        notes="" if final_status == "accepted" else _issue_summary(judge),
    )


def _discover_paper_ids(papers_root: Path) -> list[str]:
    """Return paper IDs that have a text package and are ready for pipeline.

    Only includes directories that contain 03_text_package.json — this guards
    against accidentally processing paper dirs that only have 01_paper.xml
    (XML downloaded but not yet packaged), which would cause every paper to
    land in `incomplete` with "05_agent_input.md missing".
    """
    if not papers_root.exists():
        return []
    return sorted(
        path.name
        for path in papers_root.iterdir()
        if path.is_dir() and (path / "03_text_package.json").exists()
    )


def _has_existing_pass(paper_dir: Path) -> bool:
    validation_path = paper_dir / "08_validation.json"
    judge_path = paper_dir / "09_judge.json"
    extraction_path = paper_dir / "07_extraction.json"
    if not (validation_path.exists() and judge_path.exists() and extraction_path.exists()):
        return False
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    judge = json.loads(judge_path.read_text(encoding="utf-8"))
    return validation.get("status") == "pass" and judge.get("status") == "pass"


def _has_existing_rejected(paper_dir: Path) -> bool:
    judge_path = paper_dir / "09_judge.json"
    validation_path = paper_dir / "08_validation.json"
    if not (judge_path.exists() or validation_path.exists()):
        return False
    if judge_path.exists():
        try:
            judge = json.loads(judge_path.read_text(encoding="utf-8"))
            if judge.get("status") == "fail":
                return True
        except json.JSONDecodeError:
            pass
    if validation_path.exists():
        try:
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            if validation.get("status") == "fail":
                return True
        except json.JSONDecodeError:
            pass
    return False


def _has_extraction_but_no_judge(paper_dir: Path) -> bool:
    return (
        (paper_dir / "07_extraction.json").exists()
        and not (paper_dir / "09_judge.json").exists()
    )


def _screening_is_skip(paper_dir: Path) -> bool:
    screening_path = paper_dir / "06_screening.json"
    if not screening_path.exists():
        return False
    try:
        screening = json.loads(screening_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return screening.get("decision") == "skip"



def _prepare_agent_input(paper_dir: Path, extraction_mode: str) -> None:
    if extraction_mode == "full":
        return
    package_path = paper_dir / "03_text_package.json"
    if not package_path.exists():
        return
    package = json.loads(package_path.read_text(encoding="utf-8"))
    (paper_dir / "05_agent_input.md").write_text(
        build_agent_input_markdown(package, mode=extraction_mode),
        encoding="utf-8",
    )


def _write_pipeline_reports(result: PipelineResult, output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    columns = [
        "paper_id",
        "final_status",
        "validation_status",
        "judge_status",
        "repair_attempts",
        "extraction_model",
        "judge_model",
        "repair_model",
        "notes",
    ]
    report_path = output_root / "pipeline_run_report.csv"
    merged_by_paper_id = _read_existing_report_rows(report_path, columns)
    for paper_result in result.paper_results:
        merged_by_paper_id[paper_result.paper_id] = paper_result.__dict__
    merged_rows = list(merged_by_paper_id.values())

    _write_rows(report_path, columns, merged_rows)
    _write_rows(
        output_root / "rejected_papers.csv",
        columns,
        [row for row in merged_rows if row["final_status"] == "rejected"],
    )
    _write_rows(
        output_root / "incomplete_papers.csv",
        columns,
        [row for row in merged_rows if row["final_status"] == "incomplete"],
    )


def _read_existing_report_rows(path: Path, columns: list[str]) -> dict[str, dict]:
    """Pipeline runs are often batched across many invocations (e.g. an
    overnight run split into several --paper-ids calls). Re-reading the
    previous report and merging by paper_id means each batch only updates
    the rows it actually touched, instead of wiping out every other
    paper's recorded status.
    """
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return {row["paper_id"]: {column: row.get(column, "") for column in columns} for row in reader}


def _write_rows(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})


def _issue_summary(report: dict) -> str:
    issues = report.get("issues", [])
    if not isinstance(issues, list) or not issues:
        return ""
    messages = []
    for issue in issues[:5]:
        if isinstance(issue, dict):
            messages.append(str(issue.get("message", issue)))
        else:
            messages.append(str(issue))
    return " | ".join(messages)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the MultiCat XML-first extraction pipeline.")
    parser.add_argument("--papers-root", default="papers")
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--paper-ids", nargs="*")
    parser.add_argument("--max-repair-loops", type=int, default=2)
    parser.add_argument("--skip-existing-pass", action="store_true")
    parser.add_argument("--extraction-mode", choices=["full", "ml_core"], default="full")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--paper-timeout-seconds", type=float, default=1800)
    args = parser.parse_args()

    result = run_pipeline(
        project_root=Path.cwd(),
        papers_root=Path(args.papers_root),
        output_root=Path(args.output_root),
        paper_ids=args.paper_ids,
        max_repair_loops=args.max_repair_loops,
        skip_existing_pass=args.skip_existing_pass,
        extraction_mode=args.extraction_mode,
        workers=args.workers,
        paper_timeout_seconds=args.paper_timeout_seconds,
    )
    print(
        "pipeline_status=success "
        f"accepted={len(result.accepted)} rejected={len(result.rejected)} "
        f"incomplete={len(result.incomplete)}"
    )
    print(f"pipeline_report={Path(args.output_root) / 'pipeline_run_report.csv'}")
    print(f"audit_table={result.audit_table}")
    print(f"ml_ready_table={result.ml_ready_table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
