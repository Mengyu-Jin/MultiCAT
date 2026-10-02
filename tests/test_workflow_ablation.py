from __future__ import annotations

import hashlib
import json
import csv
from pathlib import Path

from multicat.ablation.variant_runner import (
    ABLATION_VARIANTS,
    create_variant_workspaces,
    run_variant,
    select_stratified_papers,
    select_stratified_papers_by_quotas,
)
from multicat.ablation.workflow_ablation_cli import (
    prepare_raw_extraction,
    variant_is_complete,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_create_variant_workspaces_uses_identical_read_only_extraction_snapshot(
    tmp_path: Path,
):
    source = tmp_path / "source" / "P000001"
    source.mkdir(parents=True)
    payload = {
        "paper": {"paper_id": "P000001"},
        "catalysts": [],
        "reactions": [],
        "extraction_meta": {"schema_version": "v1"},
    }
    (source / "03_text_package.json").write_text("{}", encoding="utf-8")
    (source / "05_agent_input.md").write_text("input", encoding="utf-8")
    (source / "06_screening.json").write_text(
        json.dumps({"decision": "keep"}), encoding="utf-8"
    )
    (source / "07_extraction.json").write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )

    output_root = tmp_path / "ablation"
    paths = create_variant_workspaces(source, output_root)

    assert set(paths) == set(ABLATION_VARIANTS)
    raw_snapshot = output_root / "raw_extraction" / "P000001" / "07_extraction.json"
    expected_hash = _sha256(raw_snapshot)
    for variant, paper_dir in paths.items():
        assert paper_dir == output_root / "variants" / variant / "papers" / "P000001"
        assert _sha256(paper_dir / "07_extraction.json") == expected_hash

    (paths["full"] / "07_extraction.json").write_text("changed", encoding="utf-8")
    assert _sha256(raw_snapshot) == expected_hash
    assert (paths["no_judge"] / "07_extraction.json").read_text(encoding="utf-8") != "changed"


def test_create_variant_workspaces_accepts_existing_raw_snapshot(tmp_path: Path):
    raw_dir = tmp_path / "ablation" / "raw_extraction" / "P000001"
    raw_dir.mkdir(parents=True)
    (raw_dir / "07_extraction.json").write_text('{"reactions":[]}', encoding="utf-8")

    paths = create_variant_workspaces(raw_dir, tmp_path / "ablation")

    assert len(paths) == 4
    assert all((path / "07_extraction.json").exists() for path in paths.values())


def test_create_variant_workspaces_does_not_overwrite_existing_variant(tmp_path: Path):
    raw_dir = tmp_path / "ablation" / "raw_extraction" / "P000001"
    raw_dir.mkdir(parents=True)
    (raw_dir / "07_extraction.json").write_text('{"state":"raw"}', encoding="utf-8")
    existing = tmp_path / "ablation" / "variants" / "full" / "papers" / "P000001"
    existing.mkdir(parents=True)
    (existing / "07_extraction.json").write_text('{"state":"repaired"}', encoding="utf-8")

    create_variant_workspaces(raw_dir, tmp_path / "ablation")

    assert (existing / "07_extraction.json").read_text(encoding="utf-8") == '{"state":"repaired"}'


def test_ablation_variant_definitions_match_manuscript_four_branch_design():
    assert ABLATION_VARIANTS["full"].use_validation is True
    assert ABLATION_VARIANTS["full"].use_repair is True
    assert ABLATION_VARIANTS["full"].use_judge is True

    assert ABLATION_VARIANTS["no_judge"].use_validation is True
    assert ABLATION_VARIANTS["no_judge"].use_repair is True
    assert ABLATION_VARIANTS["no_judge"].use_judge is False

    assert ABLATION_VARIANTS["no_repair"].use_validation is True
    assert ABLATION_VARIANTS["no_repair"].use_repair is False
    assert ABLATION_VARIANTS["no_repair"].use_judge is True

    assert ABLATION_VARIANTS["extraction_only"].use_validation is False
    assert ABLATION_VARIANTS["extraction_only"].use_repair is False
    assert ABLATION_VARIANTS["extraction_only"].use_judge is False


class _PassingRunner:
    def __init__(self):
        self.calls: list[str] = []

    def validate(self, paper_dir: Path) -> dict:
        self.calls.append("validation")
        report = {"status": "pass", "issues": [], "stats": {}}
        (paper_dir / "08_validation.json").write_text(json.dumps(report), encoding="utf-8")
        return report

    def run_agent(self, kind: str, paper_dir: Path, project_root: Path) -> dict:
        self.calls.append(kind)
        if kind == "judge":
            report = {"status": "pass", "issues": []}
            (paper_dir / "09_judge.json").write_text(json.dumps(report), encoding="utf-8")
            return report
        if kind == "repair":
            return json.loads((paper_dir / "07_extraction.json").read_text(encoding="utf-8"))
        raise AssertionError(kind)


def test_run_variant_executes_only_enabled_components(tmp_path: Path):
    paper_dir = tmp_path / "P000001"
    paper_dir.mkdir()
    (paper_dir / "07_extraction.json").write_text(
        json.dumps({"catalysts": [], "reactions": []}), encoding="utf-8"
    )

    expected = {
        "full": ["validation", "judge"],
        "no_judge": ["validation"],
        "no_repair": ["validation", "judge"],
        "extraction_only": [],
    }
    for variant, calls in expected.items():
        runner = _PassingRunner()
        result = run_variant(
            variant=variant,
            paper_dir=paper_dir,
            project_root=tmp_path,
            runner=runner,
        )
        assert runner.calls == calls
        assert result.variant == variant
        assert result.status == "usable"


class _RejectedRepairRunner(_PassingRunner):
    def __init__(self):
        super().__init__()
        self.validation_count = 0

    def validate(self, paper_dir: Path) -> dict:
        self.calls.append("validation")
        self.validation_count += 1
        return {"status": "fail", "issues": [{"type": "missing_reaction"}]}

    def run_agent(self, kind: str, paper_dir: Path, project_root: Path) -> dict:
        self.calls.append(kind)
        if kind == "repair":
            raise ValueError("repair scope rejected")
        raise AssertionError(kind)


def test_run_variant_continues_after_rejected_repair_output(tmp_path: Path):
    paper_dir = tmp_path / "P000001"
    paper_dir.mkdir()
    (paper_dir / "07_extraction.json").write_text('{"reactions":[]}', encoding="utf-8")
    runner = _RejectedRepairRunner()

    result = run_variant(
        variant="full",
        paper_dir=paper_dir,
        project_root=tmp_path,
        runner=runner,
        max_repair_loops=2,
    )

    assert runner.calls == ["validation", "repair", "validation", "repair", "validation"]
    assert result.status == "rejected"
    assert result.repair_attempts == 2


def test_select_stratified_papers_takes_two_distinct_papers_per_product(tmp_path: Path):
    table = tmp_path / "reactions.csv"
    fieldnames = ["paper_id", "hmf_yield", "furfural_yield", "levulinic_acid_yield"]
    rows = [
        {"paper_id": "P1", "hmf_yield": "50", "furfural_yield": "", "levulinic_acid_yield": ""},
        {"paper_id": "P1", "hmf_yield": "60", "furfural_yield": "", "levulinic_acid_yield": ""},
        {"paper_id": "P2", "hmf_yield": "40", "furfural_yield": "", "levulinic_acid_yield": ""},
        {"paper_id": "P3", "hmf_yield": "", "furfural_yield": "30", "levulinic_acid_yield": ""},
        {"paper_id": "P4", "hmf_yield": "", "furfural_yield": "20", "levulinic_acid_yield": ""},
        {"paper_id": "P5", "hmf_yield": "", "furfural_yield": "", "levulinic_acid_yield": "70"},
        {"paper_id": "P6", "hmf_yield": "", "furfural_yield": "", "levulinic_acid_yield": "65"},
    ]
    with table.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    selected = select_stratified_papers(
        table,
        product_columns=tuple(fieldnames[1:]),
        papers_per_product=2,
    )

    assert selected == ["P1", "P2", "P3", "P4", "P5", "P6"]


def test_select_stratified_papers_by_quotas_returns_exact_non_overlapping_total(
    tmp_path: Path,
):
    table = tmp_path / "reactions.csv"
    fieldnames = ["paper_id", "hmf_yield", "lactic_acid_yield"]
    rows = [
        {"paper_id": "P1", "hmf_yield": "10", "lactic_acid_yield": ""},
        {"paper_id": "P2", "hmf_yield": "20", "lactic_acid_yield": ""},
        {"paper_id": "P3", "hmf_yield": "30", "lactic_acid_yield": "40"},
        {"paper_id": "P4", "hmf_yield": "", "lactic_acid_yield": "50"},
        {"paper_id": "P5", "hmf_yield": "", "lactic_acid_yield": "60"},
    ]
    with table.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    selected = select_stratified_papers_by_quotas(
        table,
        product_quotas={"hmf_yield": 2, "lactic_acid_yield": 3},
    )

    assert selected == ["P1", "P2", "P3", "P4", "P5"]
    assert len(selected) == len(set(selected)) == 5


class _ExtractionRunner:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def run_agent(self, kind: str, paper_dir: Path, project_root: Path) -> dict:
        self.calls.append((kind, paper_dir.name))
        assert kind == "extraction"
        payload = {"catalysts": [], "reactions": [{"reaction_id": "raw"}]}
        (paper_dir / "07_extraction.json").write_text(json.dumps(payload), encoding="utf-8")
        return payload


def test_prepare_raw_extraction_calls_extraction_once_in_isolated_staging(tmp_path: Path):
    source = tmp_path / "papers" / "P1"
    source.mkdir(parents=True)
    for name, text in {
        "03_text_package.json": "{}",
        "05_agent_input.md": "input",
        "06_screening.json": '{"decision":"keep"}',
    }.items():
        (source / name).write_text(text, encoding="utf-8")
    runner = _ExtractionRunner()

    raw_dir = prepare_raw_extraction(
        source_paper_dir=source,
        output_root=tmp_path / "out",
        project_root=tmp_path,
        runner=runner,
    )

    assert runner.calls == [("extraction", "P1")]
    assert raw_dir == tmp_path / "out" / "raw_extraction" / "P1"
    assert json.loads((raw_dir / "07_extraction.json").read_text(encoding="utf-8"))[
        "reactions"
    ] == [{"reaction_id": "raw"}]
    assert not (source / "07_extraction.json").exists()


def test_prepare_raw_extraction_reuses_completed_snapshot(tmp_path: Path):
    source = tmp_path / "papers" / "P1"
    source.mkdir(parents=True)
    raw_dir = tmp_path / "out" / "raw_extraction" / "P1"
    raw_dir.mkdir(parents=True)
    (raw_dir / "07_extraction.json").write_text('{"reactions":[{"id":"kept"}]}', encoding="utf-8")
    runner = _ExtractionRunner()

    returned = prepare_raw_extraction(
        source_paper_dir=source,
        output_root=tmp_path / "out",
        project_root=tmp_path,
        runner=runner,
    )

    assert returned == raw_dir
    assert runner.calls == []


def test_variant_is_complete_requires_result_and_extraction(tmp_path: Path):
    root = tmp_path / "out"
    result = root / "variants" / "full" / "results" / "P1.json"
    result.parent.mkdir(parents=True)
    result.write_text("{}", encoding="utf-8")
    assert variant_is_complete(root, "full", "P1") is False
    extraction = root / "variants" / "full" / "papers" / "P1" / "07_extraction.json"
    extraction.parent.mkdir(parents=True)
    extraction.write_text("{}", encoding="utf-8")
    assert variant_is_complete(root, "full", "P1") is True
