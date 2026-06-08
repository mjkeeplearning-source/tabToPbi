"""Remove a workbook from the regression gate and delete its snapshot.

Usage: uv run tests/regression/deregister.py <stem_or_twb_path>

Examples:
  uv run tests/regression/deregister.py simple
  uv run tests/regression/deregister.py input/simple.twb
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import yaml

_REGISTRY = Path("tests/regression/registry.yaml")


def deregister(stem_or_path: str) -> None:
    stem = Path(stem_or_path).stem  # works for both "simple" and "input/simple.twb"

    if not _REGISTRY.exists():
        print(f"Registry not found: {_REGISTRY}")
        sys.exit(1)

    data = yaml.safe_load(_REGISTRY.read_text()) or {}
    workbooks = data.get("workbooks", [])
    match = next((e for e in workbooks if e["stem"] == stem), None)

    if not match:
        print(f"'{stem}' is not registered. Registered workbooks:")
        for e in workbooks:
            print(f"  {e['stem']}")
        sys.exit(1)

    snapshot_dir = Path(match["snapshot_path"])
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
        print(f"Deleted snapshot: {snapshot_dir}")
    else:
        print(f"Snapshot directory not found (already deleted?): {snapshot_dir}")

    data["workbooks"] = [e for e in workbooks if e["stem"] != stem]
    _REGISTRY.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    print(f"Removed '{stem}' from registry: {_REGISTRY}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run tests/regression/deregister.py <stem_or_twb_path>")
        sys.exit(1)
    deregister(sys.argv[1])
