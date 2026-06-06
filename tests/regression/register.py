"""Register a workbook as a regression baseline (no Claude translation).

Usage: uv run tests/regression/register.py input/simple.twb [alias]

Optional alias shortens the snapshot directory name (useful when the workbook
filename is long and would exceed Windows MAX_PATH).
"""

import shutil
import sys
import tempfile
from pathlib import Path

# Ensure project root is importable when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import yaml

from tab_to_pbi.parser import parse, extract_twbx_data
from tab_to_pbi.transformer import transform
from tab_to_pbi.generator import generate
from tab_to_pbi.dashboard import parse_dashboards_from_path, transform_dashboards, write_dashboard_pages

_REGISTRY = Path("tests/regression/registry.yaml")
_SNAPSHOTS_DIR = Path("tests/snapshots")
_SNAPSHOT_NAMES = {"visual.json", "page.json", "report.json", "pages.json", "definition.pbir", "definition.pbism"}


def _run_pipeline(twb_path: Path, output_dir: Path) -> tuple[dict, dict]:
    """Run the deterministic pipeline (no Claude). Returns (workbook, transformed)."""
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

    return workbook, transformed


def _collect_snapshot_files(output_dir: Path, stem: str) -> dict[Path, Path]:
    """Return {relative_path: absolute_path} for all snapshot-eligible output files."""
    files = {}
    for root in [output_dir / f"{stem}.Report", output_dir / f"{stem}.SemanticModel"]:
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and (f.suffix == ".tmdl" or f.name in _SNAPSHOT_NAMES):
                files[f.relative_to(output_dir)] = f
    return files


def register(twb_path: Path, alias: str | None = None) -> None:
    stem = twb_path.stem
    snapshot_key = alias or stem
    snapshot_dir = _SNAPSHOTS_DIR / snapshot_key

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        workbook, transformed = _run_pipeline(twb_path, tmp_path)

        calc_count = len(transformed.get("report", {}).get("calculated_fields", []))
        report_dir = tmp_path / f"{stem}.Report"
        visual_count = sum(1 for _ in report_dir.rglob("visual.json")) if report_dir.exists() else 0

        files = _collect_snapshot_files(tmp_path, stem)
        print(f"Snapshotting {len(files)} files for '{stem}' (alias: {snapshot_key})")

        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)

        for rel, src in files.items():
            dest = snapshot_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            print(f"  {rel}")

    _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load(_REGISTRY.read_text()) if _REGISTRY.exists() else {}
    if not data:
        data = {}
    workbooks = [e for e in data.get("workbooks", []) if e["stem"] != stem]
    entry = {
        "stem": stem,
        "path": str(twb_path),
        "data_dir": "data",
        "expected_visual_count": visual_count,
        "expected_calc_field_count": calc_count,
        "snapshot_path": str(snapshot_dir),
    }
    if alias:
        entry["alias"] = alias
    workbooks.append(entry)
    data["workbooks"] = workbooks
    _REGISTRY.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    print(f"Registered '{stem}': {visual_count} visuals, {calc_count} calc fields")
    print(f"Registry: {_REGISTRY}")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("Usage: uv run tests/regression/register.py <workbook.twb> [alias]")
        sys.exit(1)
    alias = sys.argv[2] if len(sys.argv) == 3 else None
    register(Path(sys.argv[1]), alias=alias)
