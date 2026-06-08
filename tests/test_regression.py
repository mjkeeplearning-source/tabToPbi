"""Regression gate: re-run deterministic pipeline and diff against saved snapshots.

Register a baseline: uv run tests/regression/register.py input/simple.twb
Run checks:         uv run pytest tests/test_regression.py -x -q
"""

import difflib
import tempfile
from pathlib import Path

import pytest
import yaml

from tab_to_pbi.parser import parse, extract_twbx_data
from tab_to_pbi.transformer import transform
from tab_to_pbi.generator import generate
from tab_to_pbi.dashboard import parse_dashboards_from_path, transform_dashboards, write_dashboard_pages

_REGISTRY_PATH = Path("tests/regression/registry.yaml")
_SNAPSHOT_NAMES = {"visual.json", "page.json", "report.json", "pages.json", "definition.pbir", "definition.pbism"}


def _load_registry() -> list[dict]:
    if not _REGISTRY_PATH.exists():
        return []
    data = yaml.safe_load(_REGISTRY_PATH.read_text()) or {}
    return data.get("workbooks", [])


def _run_pipeline(twb_path: Path, output_dir: Path) -> None:
    if twb_path.suffix.lower() == ".twbx":
        data_dir = output_dir / f"{twb_path.stem}_data"
        extract_twbx_data(twb_path, data_dir)
    else:
        data_dir = twb_path.parent.parent / "data"

    workbook = parse(twb_path)
    transformed = transform(workbook, workbook_name=twb_path.stem)
    generate(transformed, output_dir, data_dir)

    dashboards = parse_dashboards_from_path(twb_path)
    dashboard_pages = transform_dashboards(dashboards, workbook, transformed)
    write_dashboard_pages(dashboard_pages, output_dir, twb_path.stem)


def _collect_files(output_dir: Path, stem: str) -> dict[str, str]:
    """Return {relative_path: content} for all snapshot-eligible output files."""
    files = {}
    for root in [output_dir / f"{stem}.Report", output_dir / f"{stem}.SemanticModel"]:
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and (f.suffix == ".tmdl" or f.name in _SNAPSHOT_NAMES):
                rel = str(f.relative_to(output_dir))
                files[rel] = f.read_text(encoding="utf-8", errors="replace")
    return files


def _collect_snapshot(snapshot_dir: Path, stem: str) -> dict[str, str]:
    """Return {relative_path: content} mirroring the output layout."""
    files = {}
    for root in [snapshot_dir / f"{stem}.Report", snapshot_dir / f"{stem}.SemanticModel"]:
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file():
                rel = str(f.relative_to(snapshot_dir))
                files[rel] = f.read_text(encoding="utf-8", errors="replace")
    return files


_registry = _load_registry()
_params = (
    _registry
    if _registry
    else [pytest.param({}, marks=pytest.mark.skip(reason="No workbooks registered in tests/regression/registry.yaml"))]
)


@pytest.mark.parametrize("entry", _params, ids=[e["stem"] for e in _registry] if _registry else ["none"])
def test_regression(entry):
    stem = entry["stem"]
    twb_path = Path(entry["path"])
    snapshot_dir = Path(entry["snapshot_path"])

    assert twb_path.exists(), f"Workbook not found: {twb_path}"
    assert snapshot_dir.exists(), f"Snapshot not found: {snapshot_dir} — re-run register.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _run_pipeline(twb_path, tmp_path)
        new_files = _collect_files(tmp_path, stem)

    snapshot_files = _collect_snapshot(snapshot_dir, stem)

    missing = set(snapshot_files) - set(new_files)
    added = set(new_files) - set(snapshot_files)

    if missing:
        pytest.fail(f"[{stem}] Files missing from new output: {sorted(missing)}")
    if added:
        pytest.fail(f"[{stem}] Unexpected new files not in snapshot: {sorted(added)}")

    for rel_path, new_content in new_files.items():
        expected = snapshot_files[rel_path]
        if new_content != expected:
            diff = "\n".join(difflib.unified_diff(
                expected.splitlines(),
                new_content.splitlines(),
                fromfile=f"snapshot/{rel_path}",
                tofile=f"current/{rel_path}",
                lineterm="",
            ))
            pytest.fail(f"[{stem}] Regression in {rel_path}:\n\n{diff}")
