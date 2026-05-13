# Visual Mapping Agent Implementation Plan

> **Execution approach:** Inline execution via `superpowers:executing-plans` in a single session with checkpoints for review.

**Goal:** Build an offline registry builder (`visual_agent.py`) that scans existing pipeline output to auto-generate `samples/visual_mappings.json` and regenerate `docs/visual_conversion.md`, then wire a thin runtime reader (`visual_mapper.py`) into the pipeline so hardcoded visual dicts are replaced by registry lookups with hardcoded fallbacks.

**Architecture:** Three phases — P1 builds the offline agent with no pipeline changes; P2 adds provenance fields and wires the registry into the pipeline; P3 adds an advisory runtime suggestion mode. `visual_agent.py` is the sole writer of `samples/visual_mappings.json`. No pipeline run ever mutates the canonical registry.

**Tech Stack:** Python 3.12+, `pyyaml` (new dependency), `jsonschema` (existing), `anthropic` (existing), `pathlib`/`json` (stdlib). Commands: `uv run tab_to_pbi/visual_agent.py`, `uv run pytest tests/`.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `samples/validation_manifest.yaml` | Create | User-maintained: declares PBI-validated sheets per workbook |
| `samples/baselines/<type>_minimal.json` | Create (8 files) | Curated minimal PBI visual.json per visual type for object diffing |
| `samples/visual_mappings.json` | Generated output | Machine-readable registry — written only by `visual_agent.py` |
| `tab_to_pbi/visual_agent.py` | Create | Offline builder: scan → extract → fill gaps → write registry + doc |
| `tab_to_pbi/visual_mapper.py` | Create | Thin runtime reader: registry lookups only, no Claude, no assembly |
| `tests/test_visual_agent.py` | Create | Unit tests for agent scan/extract/write functions |
| `tests/test_visual_mapper.py` | Create | Unit tests for runtime reader functions |
| `tab_to_pbi/generator.py` | Modify (P2) | Add `_provenance` fields to every emitted `visual.json` |
| `tab_to_pbi/transformer.py` | Modify (P2) | Consult registry for mark-type lookup; fall back to `MARK_TO_VISUAL` |
| `tab_to_pbi/main.py` | Modify (P2) | Call `load_registry()` at startup |

---

## Phase 1 — Offline Builder (no pipeline changes)

---

### Task 1: Add pyyaml + create samples directory structure

**Files:**
- Modify: `pyproject.toml`
- Create: `samples/validation_manifest.yaml`
- Create: `samples/baselines/` (empty directory)

- [ ] **Step 1.1: Add pyyaml dependency**

```bash
cd C:/vibe_coding/tabToPbi && uv add pyyaml
```

Expected: `pyproject.toml` gains `pyyaml>=6.0` in dependencies.

- [ ] **Step 1.2: Create samples/validation_manifest.yaml**

Create `samples/validation_manifest.yaml`:

```yaml
# Declare which sheets/dashboards have been verified in PBI Desktop.
# visual_agent.py assigns status: "validated" to registry entries from these sheets.
# All other discovered entries get status: "generated".
workbooks:
  - file: input/daatabricks.twb
    validated_sheets:
      - "Product Performance"
      - "Revenue Trend"
      - "Customer KPI"
    validated_dashboards:
      - "Company Dashboard"
```

- [ ] **Step 1.3: Create samples/baselines placeholder**

```bash
mkdir C:/vibe_coding/tabToPbi/samples/baselines
```

- [ ] **Step 1.4: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add pyproject.toml samples/validation_manifest.yaml && git commit -m "feat: add pyyaml dependency and validation_manifest.yaml scaffold"
```

---

### Task 2: Curate minimal baselines per visual type

Baselines are the bare minimum `visual.json` objects block for each visual type with zero Tableau-driven formatting. Diffing against these removes PBI noise.

**Files:**
- Create: `samples/baselines/barChart_minimal.json`
- Create: `samples/baselines/columnChart_minimal.json`
- Create: `samples/baselines/lineChart_minimal.json`
- Create: `samples/baselines/areaChart_minimal.json`
- Create: `samples/baselines/pieChart_minimal.json`
- Create: `samples/baselines/tableEx_minimal.json`
- Create: `samples/baselines/pivotTable_minimal.json`
- Create: `samples/baselines/cardVisual_minimal.json`

- [ ] **Step 2.1: Write failing test**

Create `tests/test_visual_agent.py`:

```python
"""Tests for visual_agent.py — offline registry builder."""
import json
from pathlib import Path
from tab_to_pbi.visual_agent import load_baselines

BASELINES_DIR = Path("samples/baselines")


def test_load_baselines_returns_dict_for_all_visual_types():
    baselines = load_baselines()
    expected = {
        "barChart", "columnChart", "lineChart", "areaChart",
        "pieChart", "tableEx", "pivotTable", "cardVisual",
    }
    assert set(baselines.keys()) == expected


def test_each_baseline_is_valid_json_dict():
    baselines = load_baselines()
    for vtype, baseline in baselines.items():
        assert isinstance(baseline, dict), f"{vtype} baseline is not a dict"
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v
```

Expected: `ModuleNotFoundError: No module named 'tab_to_pbi.visual_agent'`

- [ ] **Step 2.3: Create samples/baselines files**

Create `samples/baselines/barChart_minimal.json`:
```json
{"objects": {}}
```

Create `samples/baselines/columnChart_minimal.json`:
```json
{"objects": {}}
```

Create `samples/baselines/lineChart_minimal.json`:
```json
{"objects": {}}
```

Create `samples/baselines/areaChart_minimal.json`:
```json
{"objects": {}}
```

Create `samples/baselines/pieChart_minimal.json`:
```json
{"objects": {}}
```

Create `samples/baselines/tableEx_minimal.json`:
```json
{"objects": {}}
```

Create `samples/baselines/pivotTable_minimal.json`:
```json
{"objects": {}}
```

Create `samples/baselines/cardVisual_minimal.json`:
```json
{"objects": {}}
```

- [ ] **Step 2.4: Create tab_to_pbi/visual_agent.py scaffold with load_baselines()**

Create `tab_to_pbi/visual_agent.py`:

```python
"""Offline registry builder for visual property mappings.

Run: uv run tab_to_pbi/visual_agent.py
Sole writer of samples/visual_mappings.json.
"""
import json
from pathlib import Path

import yaml

_SAMPLES_DIR = Path("samples")
_OUTPUT_DIR = Path("output")
_REGISTRY_FILE = _SAMPLES_DIR / "visual_mappings.json"
_BASELINES_DIR = _SAMPLES_DIR / "baselines"
_MANIFEST_FILE = _SAMPLES_DIR / "validation_manifest.yaml"
_VISUAL_CONVERSION_DOC = Path("docs/visual_conversion.md")

_ALL_VISUAL_TYPES = {
    "barChart", "columnChart", "lineChart", "areaChart",
    "pieChart", "tableEx", "pivotTable", "cardVisual",
}


def load_baselines() -> dict[str, dict]:
    """Load per-visual-type minimal baselines from samples/baselines/."""
    baselines = {}
    for vtype in _ALL_VISUAL_TYPES:
        path = _BASELINES_DIR / f"{vtype}_minimal.json"
        if path.exists():
            baselines[vtype] = json.loads(path.read_text())
    return baselines


if __name__ == "__main__":
    print("visual_agent: scaffold only — tasks not yet implemented")
```

- [ ] **Step 2.5: Run tests**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 2.6: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add samples/baselines/ tab_to_pbi/visual_agent.py tests/test_visual_agent.py && git commit -m "feat: add baselines and visual_agent.py scaffold with load_baselines()"
```

---

### Task 3: load_manifest() + scan_output_pairs()

**Files:**
- Modify: `tab_to_pbi/visual_agent.py`
- Modify: `tests/test_visual_agent.py`

- [ ] **Step 3.1: Append failing tests**

Append to `tests/test_visual_agent.py`:

```python
import tempfile
from tab_to_pbi.visual_agent import load_manifest, scan_output_pairs


def _write_manifest(tmp: Path, workbooks: list) -> None:
    (tmp / "samples").mkdir(exist_ok=True)
    content = {"workbooks": workbooks}
    (tmp / "samples" / "validation_manifest.yaml").write_text(
        yaml.dump(content), encoding="utf-8"
    )


def _make_transformed(tmp: Path, stem: str, visuals: list) -> None:
    (tmp / "output").mkdir(exist_ok=True)
    data = {"visuals": visuals}
    (tmp / "output" / f"{stem}.transformed.json").write_text(json.dumps(data))


def _make_visual_json(tmp: Path, stem: str, section: str, visual_name: str,
                      display_name: str, visual_type: str) -> None:
    page_dir = tmp / "output" / f"{stem}.Report" / "definition" / "pages" / section
    vis_dir = page_dir / "visuals" / visual_name
    vis_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "page.json").write_text(json.dumps({
        "displayName": display_name, "name": section,
    }))
    (vis_dir / "visual.json").write_text(json.dumps({
        "name": visual_name,
        "visual": {"visualType": visual_type, "query": {"queryState": {}}, "objects": {}},
    }))


def test_load_manifest_validated_lookup():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write_manifest(tmp, [
            {"file": "input/foo.twb", "validated_sheets": ["Sheet1", "Sheet2"],
             "validated_dashboards": ["Dash1"]},
        ])
        result = load_manifest(manifest_path=tmp / "samples" / "validation_manifest.yaml")
        assert result["foo"]["sheets"] == {"Sheet1", "Sheet2"}
        assert result["foo"]["dashboards"] == {"Dash1"}


def test_scan_output_pairs_finds_pair():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write_manifest(tmp, [
            {"file": "input/myworkbook.twb", "validated_sheets": ["SalesSheet"]},
        ])
        _make_transformed(tmp, "myworkbook", [
            {"name": "SalesSheet", "page_name": "SalesSheet", "mark_type": "Bar",
             "row_fields": [], "col_fields": [], "show_data_labels": False},
        ])
        _make_visual_json(tmp, "myworkbook", "ReportSection1", "visual_1",
                          "SalesSheet", "barChart")
        validated = load_manifest(manifest_path=tmp / "samples" / "validation_manifest.yaml")
        pairs = scan_output_pairs(validated, output_dir=tmp / "output")
        assert len(pairs) == 1
        assert pairs[0]["sheet_name"] == "SalesSheet"
        assert pairs[0]["status"] == "validated"
        assert pairs[0]["pbi"]["visual"]["visualType"] == "barChart"


def test_scan_output_pairs_unvalidated_sheet_gets_generated_status():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _write_manifest(tmp, [
            {"file": "input/myworkbook.twb", "validated_sheets": []},
        ])
        _make_transformed(tmp, "myworkbook", [
            {"name": "UnvalidatedSheet", "page_name": "UnvalidatedSheet", "mark_type": "Line",
             "row_fields": [], "col_fields": [], "show_data_labels": False},
        ])
        _make_visual_json(tmp, "myworkbook", "ReportSection1", "visual_1",
                          "UnvalidatedSheet", "lineChart")
        validated = load_manifest(manifest_path=tmp / "samples" / "validation_manifest.yaml")
        pairs = scan_output_pairs(validated, output_dir=tmp / "output")
        assert pairs[0]["status"] == "generated"
```

Add `import yaml` at the top of the test file.

- [ ] **Step 3.2: Run to verify failures**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v -k "test_load_manifest or test_scan"
```

Expected: FAIL — `load_manifest` and `scan_output_pairs` not defined.

- [ ] **Step 3.3: Implement load_manifest() and scan_output_pairs() in visual_agent.py**

Add after `load_baselines()`:

```python
def load_manifest(manifest_path: Path | None = None) -> dict[str, dict]:
    """Parse validation_manifest.yaml → {workbook_stem: {sheets: set, dashboards: set}}."""
    path = manifest_path or _MANIFEST_FILE
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    result = {}
    for wb in data.get("workbooks", []):
        stem = Path(wb["file"]).stem
        result[stem] = {
            "sheets": set(wb.get("validated_sheets", [])),
            "dashboards": set(wb.get("validated_dashboards", [])),
        }
    return result


def scan_output_pairs(
    validated: dict[str, dict],
    output_dir: Path | None = None,
) -> list[dict]:
    """Scan output/ for (transformed.json, visual.json) pairs.

    Matches via _provenance fields when present (P2+), else falls back
    to page.json displayName matching.
    """
    out = output_dir or _OUTPUT_DIR
    pairs = []
    for transformed_path in sorted(out.glob("*.transformed.json")):
        stem = transformed_path.name.replace(".transformed.json", "")
        transformed = json.loads(transformed_path.read_text())
        report_dir = out / f"{stem}.Report"
        if not report_dir.exists():
            continue
        pages_dir = report_dir / "definition" / "pages"
        if not pages_dir.exists():
            continue
        # Build page_name → visual_info lookup from transformed
        sheet_lookup = {v["page_name"]: v for v in transformed.get("visuals", [])}
        validated_sheets = validated.get(stem, {}).get("sheets", set())

        for page_dir in sorted(pages_dir.iterdir()):
            if not page_dir.is_dir():
                continue
            page_json_path = page_dir / "page.json"
            if not page_json_path.exists():
                continue
            page_data = json.loads(page_json_path.read_text())
            display_name = page_data.get("displayName", "")
            source_visual = sheet_lookup.get(display_name)
            if not source_visual:
                continue
            visuals_dir = page_dir / "visuals"
            if not visuals_dir.exists():
                continue
            for visual_dir in sorted(visuals_dir.iterdir()):
                vpath = visual_dir / "visual.json"
                if not vpath.exists():
                    continue
                pbi_json = json.loads(vpath.read_text())
                # Use _provenance if present, else display_name
                prov = pbi_json.get("_provenance", {})
                sheet_name = prov.get("source_sheet_name") or display_name
                status = "validated" if sheet_name in validated_sheets else "generated"
                pairs.append({
                    "stem": stem,
                    "sheet_name": sheet_name,
                    "status": status,
                    "tableau": source_visual,
                    "pbi": pbi_json,
                })
    return pairs
```

- [ ] **Step 3.4: Run tests**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v
```

Expected: All tests PASS.

- [ ] **Step 3.5: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/visual_agent.py tests/test_visual_agent.py && git commit -m "feat: add load_manifest() and scan_output_pairs() to visual_agent"
```

---

### Task 4: extract_mark_type_mapping() + extract_query_roles()

**Files:**
- Modify: `tab_to_pbi/visual_agent.py`
- Modify: `tests/test_visual_agent.py`

- [ ] **Step 4.1: Append failing tests**

```python
from tab_to_pbi.visual_agent import extract_mark_type_mapping, extract_query_roles
from tab_to_pbi.generator import _VISUAL_ROLES


def _make_pair(mark_type: str, visual_type: str, status: str = "validated",
               row_fields=None, col_fields=None) -> dict:
    return {
        "stem": "test_wb", "sheet_name": "TestSheet", "status": status,
        "tableau": {
            "mark_type": mark_type,
            "row_fields": row_fields or [],
            "col_fields": col_fields or [],
            "show_data_labels": False,
        },
        "pbi": {
            "visual": {"visualType": visual_type, "objects": {}},
        },
    }


def test_extract_mark_type_mapping_basic():
    pairs = [_make_pair("Bar", "barChart", "validated")]
    result = extract_mark_type_mapping(pairs)
    assert result["Bar"]["pbi_visual_type"] == "barChart"
    assert result["Bar"]["status"] == "validated"
    assert result["Bar"]["source"]["workbook"] == "test_wb"


def test_extract_mark_type_mapping_no_downgrade():
    pairs = [
        _make_pair("Line", "lineChart", "validated"),
        _make_pair("Line", "lineChart", "generated"),
    ]
    result = extract_mark_type_mapping(pairs)
    assert result["Line"]["status"] == "validated"


def test_extract_mark_type_mapping_generated_when_not_validated():
    pairs = [_make_pair("Pie", "pieChart", "generated")]
    result = extract_mark_type_mapping(pairs)
    assert result["Pie"]["status"] == "generated"


def test_extract_query_roles_bar_chart():
    pairs = [
        _make_pair("Bar", "barChart", "validated",
                   row_fields=[{"name": "Region", "is_measure": False}],
                   col_fields=[{"name": "Sum Sales", "is_measure": True}])
    ]
    result = extract_query_roles(pairs)
    assert "barChart" in result
    roles = result["barChart"]["query_roles"]
    assert roles["Category"]["tableau_shelf"] == "row"
    assert roles["Y"]["tableau_shelf"] == "col"
```

- [ ] **Step 4.2: Run to verify failures**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v -k "test_extract_mark or test_extract_query"
```

Expected: FAIL — `extract_mark_type_mapping` not defined.

- [ ] **Step 4.3: Implement extract_mark_type_mapping() and extract_query_roles()**

Add to `tab_to_pbi/visual_agent.py`:

```python
def extract_mark_type_mapping(pairs: list[dict]) -> dict:
    """Build mark_type_mapping registry section from output pairs.

    Never downgrades an existing 'validated' entry to 'generated'.
    """
    mapping: dict[str, dict] = {}
    for pair in pairs:
        mark_type = pair["tableau"].get("mark_type", "")
        visual_type = pair["pbi"].get("visual", {}).get("visualType", "")
        if not mark_type or not visual_type:
            continue
        existing = mapping.get(mark_type)
        if existing and existing["status"] == "validated" and pair["status"] != "validated":
            continue
        mapping[mark_type] = {
            "pbi_visual_type": visual_type,
            "status": pair["status"],
            "source": {"workbook": pair["stem"], "sheet": pair["sheet_name"]},
        }
    return mapping


# Maps visual_type → (cat_role, val_role, cat_shelf, val_shelf) — same as generator._VISUAL_ROLES
_ROLE_TEMPLATE: dict[str, dict] = {
    "barChart":    {"Category": "row",   "Y":        "col"},
    "columnChart": {"Category": "col",   "Y":        "row"},
    "lineChart":   {"Category": "col",   "Y":        "row"},
    "areaChart":   {"Category": "col",   "Y":        "row"},
    "pieChart":    {"Category": "row",   "Y":        "col"},
    "scatterChart":{"X":        "col",   "Y":        "row"},
    "map":         {"Location": "row",   "Size":     "col"},
    "filledMap":   {"Location": "row",   "Size":     "col"},
    "cardVisual":  {"Data":     "col"},
    "pivotTable":  {"Columns":  "col",   "Values":   "crosstab_measures"},
    "tableEx":     {"Values":   "both"},
}


def extract_query_roles(pairs: list[dict]) -> dict:
    """Build visual_types[*].query_roles from known role templates and pair statuses."""
    result: dict[str, dict] = {}
    for pair in pairs:
        visual_type = pair["pbi"].get("visual", {}).get("visualType", "")
        if not visual_type or visual_type in result:
            continue
        template = _ROLE_TEMPLATE.get(visual_type)
        if not template:
            continue
        roles = {
            role: {"tableau_shelf": shelf, "field_type": "measure" if role in ("Y", "Size", "Data", "Values") else "dimension"}
            for role, shelf in template.items()
        }
        result[visual_type] = {
            "query_roles": roles,
            "status": pair["status"],
            "source": {"workbook": pair["stem"], "sheet": pair["sheet_name"]},
        }
    return result
```

- [ ] **Step 4.4: Run tests**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v
```

Expected: All tests PASS.

- [ ] **Step 4.5: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/visual_agent.py tests/test_visual_agent.py && git commit -m "feat: add extract_mark_type_mapping() and extract_query_roles()"
```

---

### Task 5: extract_objects() with baseline diff + schema validation

**Files:**
- Modify: `tab_to_pbi/visual_agent.py`
- Modify: `tests/test_visual_agent.py`

- [ ] **Step 5.1: Append failing tests**

```python
from tab_to_pbi.visual_agent import extract_objects


def test_extract_objects_above_baseline_captured():
    baselines = {"barChart": {"objects": {}}}
    pairs = [_make_pair("Bar", "barChart", "validated")]
    pairs[0]["pbi"]["visual"]["objects"] = {
        "labels": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}]
    }
    pairs[0]["tableau"]["show_data_labels"] = True
    result = extract_objects(pairs, baselines)
    assert "barChart" in result
    assert "labels" in result["barChart"]
    assert result["barChart"]["labels"]["status"] == "validated"


def test_extract_objects_baseline_noise_excluded():
    # objects identical to baseline → not captured
    baselines = {"barChart": {"objects": {"labels": [{"properties": {}}]}}}
    pairs = [_make_pair("Bar", "barChart", "validated")]
    pairs[0]["pbi"]["visual"]["objects"] = {"labels": [{"properties": {}}]}
    result = extract_objects(pairs, baselines)
    assert result.get("barChart", {}).get("labels") is None


def test_extract_objects_pivottable_valuesOnRow():
    baselines = {"pivotTable": {"objects": {}}}
    pair = {
        "stem": "test_wb", "sheet_name": "CrossTab", "status": "validated",
        "tableau": {"mark_type": "CrossTab", "row_fields": [],
                    "crosstab_measures": [{"name": "Sum profit"}], "show_data_labels": False},
        "pbi": {"visual": {"visualType": "pivotTable", "objects": {
            "values": [{"properties": {"valuesOnRow": {"expr": {"Literal": {"Value": "true"}}}}}],
            "subTotals": [{"properties": {
                "rowSubtotals": {"expr": {"Literal": {"Value": "false"}}},
                "columnSubtotals": {"expr": {"Literal": {"Value": "false"}}},
            }}],
        }}},
    }
    result = extract_objects([pair], baselines)
    assert "pivotTable" in result
    assert "values" in result["pivotTable"]
    assert "subTotals" in result["pivotTable"]
```

- [ ] **Step 5.2: Run to verify failures**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v -k "test_extract_objects"
```

Expected: FAIL — `extract_objects` not defined.

- [ ] **Step 5.3: Implement extract_objects()**

Add to `tab_to_pbi/visual_agent.py`:

```python
import jsonschema

_PBIR_SCHEMA_CACHE = Path(".pbir_schema_cache")
_OBJ_SCHEMA_KEY = "developer-microsoft-com-json-schemas-fabric-item-report-definition-visualConfiguration-2-3-0-schema-json"


def _load_pbir_schema() -> dict | None:
    path = _PBIR_SCHEMA_CACHE / f"{_OBJ_SCHEMA_KEY}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _schema_validate(fragment: dict, schema: dict | None) -> bool:
    if not schema:
        return False
    try:
        jsonschema.validate(fragment, schema)
        return True
    except jsonschema.ValidationError:
        return False


def extract_objects(pairs: list[dict], baselines: dict[str, dict]) -> dict:
    """Extract above-baseline PBI objects fragments per visual type.

    Returns {visual_type: {obj_key: {pbi_json, trigger, status, source, schema_validated}}}.
    Never downgrades an existing 'validated' entry.
    """
    schema = _load_pbir_schema()
    result: dict[str, dict] = {}

    for pair in pairs:
        visual_type = pair["pbi"].get("visual", {}).get("visualType", "")
        if not visual_type:
            continue
        pbi_objects = pair["pbi"].get("visual", {}).get("objects", {})
        baseline_objects = baselines.get(visual_type, {}).get("objects", {})

        for obj_key, obj_val in pbi_objects.items():
            if obj_val == baseline_objects.get(obj_key):
                continue  # identical to baseline — noise, skip
            existing = result.get(visual_type, {}).get(obj_key)
            if existing and existing["status"] == "validated" and pair["status"] != "validated":
                continue
            fragment = {obj_key: obj_val}
            validated_flag = _schema_validate({"objects": fragment}, schema)
            entry = {
                "pbi_json": fragment,
                "trigger": _infer_trigger(obj_key, pair["tableau"]),
                "status": pair["status"],
                "source": {"workbook": pair["stem"], "sheet": pair["sheet_name"]},
                "schema_validated": validated_flag,
                "schema_ref": "fabric/item/report/definition/visualConfiguration/2.3.0/schema.json",
            }
            result.setdefault(visual_type, {})[obj_key] = entry

    return result


def _infer_trigger(obj_key: str, tableau: dict) -> str:
    if obj_key == "labels":
        return "show_data_labels == true"
    if obj_key == "values":
        return "crosstab_measures_non_empty AND row_fields_empty"
    if obj_key == "subTotals":
        return "always"
    return "always"
```

- [ ] **Step 5.4: Run tests**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v
```

Expected: All tests PASS.

- [ ] **Step 5.5: Full suite check**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/ -v --ignore=tests/test_pbi_desktop.py --ignore=tests/test_pbi_e2e_open.py 2>&1 | tail -5
```

Expected: All pre-existing tests still pass.

- [ ] **Step 5.6: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/visual_agent.py tests/test_visual_agent.py && git commit -m "feat: add extract_objects() with baseline diff and schema validation"
```

---

### Task 6: fill_gaps_with_claude() for inferred visual types

**Files:**
- Modify: `tab_to_pbi/visual_agent.py`
- Modify: `tests/test_visual_agent.py`

- [ ] **Step 6.1: Append failing tests**

```python
from unittest.mock import patch, MagicMock
from tab_to_pbi.visual_agent import fill_gaps_with_claude


def test_fill_gaps_skips_visual_types_already_in_registry():
    existing_registry = {
        "mark_type_mapping": {"Bar": {"pbi_visual_type": "barChart", "status": "validated", "source": {}}},
        "visual_types": {"barChart": {"query_roles": {}, "status": "validated"}},
    }
    result = fill_gaps_with_claude(existing_registry)
    # barChart already present — Claude should not be called for it
    assert result == existing_registry


def test_fill_gaps_adds_inferred_entry_for_missing_type():
    existing_registry = {
        "mark_type_mapping": {},
        "visual_types": {},
    }
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "pbi_visual_type": "filledMap",
        "query_roles": {"Location": {"tableau_shelf": "row", "field_type": "dimension"}},
        "confidence": 0.7,
    }))]
    with patch("tab_to_pbi.visual_agent._call_claude", return_value=mock_response):
        result = fill_gaps_with_claude(
            existing_registry,
            target_mark_types=["Polygon"],
        )
    assert result["mark_type_mapping"].get("Polygon", {}).get("status") == "inferred"
    assert result["mark_type_mapping"]["Polygon"]["score"] == 0.7
```

- [ ] **Step 6.2: Run to verify failures**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v -k "test_fill_gaps"
```

Expected: FAIL — `fill_gaps_with_claude` not defined.

- [ ] **Step 6.3: Implement fill_gaps_with_claude()**

Add to `tab_to_pbi/visual_agent.py`:

```python
import os
import anthropic

_CLAUDE_MODEL = "claude-opus-4-7"

# Mark types that have a known PBI visual type to infer gaps for
_ALL_MARK_TYPES = list({
    "Bar", "Column", "Line", "Area", "Pie", "Text", "CrossTab", "KPI",
    "Circle", "Shape", "Polygon", "Multipolygon", "PolyLine",
})


def _call_claude(prompt: str) -> object:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )


def fill_gaps_with_claude(
    registry: dict,
    target_mark_types: list[str] | None = None,
) -> dict:
    """For mark types missing from registry, infer mapping via Claude.

    Adds entries with status='inferred' and a float score.
    Does not overwrite existing entries of any status.
    """
    mark_types = target_mark_types or _ALL_MARK_TYPES
    existing_marks = set(registry.get("mark_type_mapping", {}).keys())
    missing = [mt for mt in mark_types if mt not in existing_marks]
    if not missing:
        return registry

    # Find nearest validated sample for grounding
    sample_entry = next(
        (v for v in registry.get("mark_type_mapping", {}).values()
         if v.get("status") == "validated"),
        None,
    )
    sample_context = f"Nearest validated sample: {json.dumps(sample_entry)}" if sample_entry else ""

    for mark_type in missing:
        prompt = (
            f"You are mapping Tableau mark types to Power BI PBIR visual types.\n"
            f"Tableau mark type: '{mark_type}'\n"
            f"{sample_context}\n"
            f"PBI PBIR objects use the structure: "
            f'{{\"objects\": {{\"key\": [{{\"properties\": {{\"prop\": {{\"expr\": {{\"Literal\": {{\"Value\": \"val\"}}}}}}}}}}]}}}}\n'
            f"Return a JSON object with keys: pbi_visual_type (string), "
            f"query_roles (dict of role->tableau_shelf), confidence (float 0-1).\n"
            f"Return only the JSON object, no other text."
        )
        try:
            response = _call_claude(prompt)
            raw = response.content[0].text.strip()
            data = json.loads(raw)
            score = float(data.get("confidence", 0.5))
            registry.setdefault("mark_type_mapping", {})[mark_type] = {
                "pbi_visual_type": data.get("pbi_visual_type", "tableEx"),
                "status": "inferred",
                "score": score,
                "source": {"workbook": "", "sheet": ""},
            }
        except Exception as exc:
            print(f"  warning: Claude inference failed for {mark_type}: {exc}")

    return registry
```

- [ ] **Step 6.4: Run tests**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v
```

Expected: All tests PASS.

- [ ] **Step 6.5: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/visual_agent.py tests/test_visual_agent.py && git commit -m "feat: add fill_gaps_with_claude() for inferred visual types"
```

---

### Task 7: write_registry() + regenerate_visual_conversion_md() + __main__ wiring

**Files:**
- Modify: `tab_to_pbi/visual_agent.py`
- Modify: `tests/test_visual_agent.py`

- [ ] **Step 7.1: Append failing tests**

```python
from tab_to_pbi.visual_agent import write_registry, regenerate_visual_conversion_md


def test_write_registry_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "samples").mkdir()
        registry = {
            "version": "1.0.0",
            "mark_type_mapping": {"Bar": {"pbi_visual_type": "barChart", "status": "validated", "source": {}}},
            "automatic_inference_rules": [],
            "visual_types": {},
            "property_mappings": {},
        }
        write_registry(registry, registry_path=tmp / "samples" / "visual_mappings.json")
        result = json.loads((tmp / "samples" / "visual_mappings.json").read_text())
        assert result["mark_type_mapping"]["Bar"]["pbi_visual_type"] == "barChart"
        assert "generated_at" in result


def test_write_registry_never_downgrades_validated():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "samples").mkdir()
        reg_path = tmp / "samples" / "visual_mappings.json"
        # Write initial registry with validated entry
        initial = {
            "version": "1.0.0", "generated_at": "old",
            "mark_type_mapping": {"Bar": {"pbi_visual_type": "barChart", "status": "validated", "source": {}}},
            "automatic_inference_rules": [], "visual_types": {}, "property_mappings": {},
        }
        reg_path.write_text(json.dumps(initial))
        # Attempt to write with generated entry for same key
        new_registry = {
            "version": "1.0.0", "generated_at": "new",
            "mark_type_mapping": {"Bar": {"pbi_visual_type": "barChart", "status": "generated", "source": {}}},
            "automatic_inference_rules": [], "visual_types": {}, "property_mappings": {},
        }
        write_registry(new_registry, registry_path=reg_path)
        result = json.loads(reg_path.read_text())
        assert result["mark_type_mapping"]["Bar"]["status"] == "validated"


def test_regenerate_doc_creates_markdown():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        registry = {
            "mark_type_mapping": {
                "Bar": {"pbi_visual_type": "barChart", "status": "validated", "source": {}},
            },
            "automatic_inference_rules": [],
            "visual_types": {},
            "property_mappings": {},
        }
        doc_path = tmp / "visual_conversion.md"
        regenerate_visual_conversion_md(registry, doc_path=doc_path)
        content = doc_path.read_text()
        assert "barChart" in content
        assert "[validated]" in content
        assert "Visual Type Mapping" in content
```

- [ ] **Step 7.2: Run to verify failures**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v -k "test_write_registry or test_regenerate"
```

Expected: FAIL.

- [ ] **Step 7.3: Implement write_registry(), regenerate_visual_conversion_md(), and __main__**

Add to `tab_to_pbi/visual_agent.py`:

```python
from datetime import datetime, timezone


def write_registry(
    registry: dict,
    registry_path: Path | None = None,
) -> None:
    """Write visual_mappings.json. Never downgrades 'validated' entries from existing file."""
    path = registry_path or _REGISTRY_FILE
    registry["generated_at"] = datetime.now(timezone.utc).isoformat()

    # Merge with existing: never downgrade validated → generated/inferred
    if path.exists():
        existing = json.loads(path.read_text())
        for section in ("mark_type_mapping", "visual_types", "property_mappings"):
            for key, existing_entry in existing.get(section, {}).items():
                new_entry = registry.get(section, {}).get(key)
                if existing_entry.get("status") == "validated" and new_entry and new_entry.get("status") != "validated":
                    registry.setdefault(section, {})[key] = existing_entry

    path.write_text(json.dumps(registry, indent=2))


def regenerate_visual_conversion_md(
    registry: dict,
    doc_path: Path | None = None,
) -> None:
    """Regenerate docs/visual_conversion.md from registry. Never hand-edit this file."""
    path = doc_path or _VISUAL_CONVERSION_DOC
    lines = [
        "# Tableau → Power BI Visual & Property Conversion Reference",
        "",
        "> Auto-generated by `visual_agent.py`. Do not edit manually.",
        "> Run `uv run tab_to_pbi/visual_agent.py` to regenerate.",
        "",
        "---",
        "",
        "## Visual Type Mapping",
        "",
        "| Tableau Mark Type | PBI Visual Type | Status |",
        "|-------------------|-----------------|--------|",
    ]
    for mark_type, entry in sorted(registry.get("mark_type_mapping", {}).items()):
        pbi_type = entry.get("pbi_visual_type") or "*(inferred)*"
        status = entry.get("status", "unknown")
        lines.append(f"| `{mark_type}` | `{pbi_type}` | [{status}] |")

    lines += [
        "",
        "---",
        "",
        "## queryState Role Mapping",
        "",
    ]
    for vtype, ventry in sorted(registry.get("visual_types", {}).items()):
        status = ventry.get("status", "unknown")
        lines += [
            f"### {vtype} [{status}]",
            "",
            "| PBI Role | Tableau Source | Field type |",
            "|----------|---------------|------------|",
        ]
        for role, rentry in ventry.get("query_roles", {}).items():
            lines.append(f"| `{role}` | {rentry.get('tableau_shelf')} shelf | {rentry.get('field_type')} |")
        lines.append("")

    lines += [
        "---",
        "",
        "## Visual Properties Mapping",
        "",
        "| Tableau property | PBI objects key | Status |",
        "|------------------|----------------|--------|",
    ]
    for prop, pentry in sorted(registry.get("property_mappings", {}).items()):
        status = pentry.get("status", "unknown")
        pbi_key = pentry.get("pbi_objects_key") or pentry.get("pbi_key", "")
        lines.append(f"| `{prop}` | `{pbi_key}` | [{status}] |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

Replace the `if __name__ == "__main__":` block with:

```python
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print("visual_agent: loading manifest...")
    validated = load_manifest()

    print("visual_agent: loading baselines...")
    baselines = load_baselines()

    print("visual_agent: scanning output pairs...")
    pairs = scan_output_pairs(validated)
    print(f"  found {len(pairs)} pairs")

    print("visual_agent: extracting mark type mapping...")
    mark_map = extract_mark_type_mapping(pairs)

    print("visual_agent: extracting query roles...")
    vtype_map = extract_query_roles(pairs)

    print("visual_agent: extracting objects...")
    objects_map = extract_objects(pairs, baselines)

    # Merge objects into visual_types
    for vtype, objs in objects_map.items():
        vtype_map.setdefault(vtype, {}).setdefault("objects", {}).update(objs)

    registry: dict = {
        "version": "1.0.0",
        "mark_type_mapping": mark_map,
        "automatic_inference_rules": [],
        "visual_types": vtype_map,
        "property_mappings": {},
    }

    print("visual_agent: filling gaps with Claude for missing visual types...")
    registry = fill_gaps_with_claude(registry)

    print("visual_agent: writing registry...")
    write_registry(registry)
    print(f"  written: {_REGISTRY_FILE}")

    print("visual_agent: regenerating visual_conversion.md...")
    regenerate_visual_conversion_md(registry)
    print(f"  written: {_VISUAL_CONVERSION_DOC}")

    print("visual_agent: done.")
```

- [ ] **Step 7.4: Run tests**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v
```

Expected: All tests PASS.

- [ ] **Step 7.5: Run visual_agent.py end-to-end**

```bash
cd C:/vibe_coding/tabToPbi && uv run tab_to_pbi/visual_agent.py
```

Expected output: lines like `found N pairs`, `written: samples/visual_mappings.json`, `written: docs/visual_conversion.md`.

Check outputs:
```bash
cd C:/vibe_coding/tabToPbi && uv run python -c "import json; r=json.load(open('samples/visual_mappings.json')); print(list(r['mark_type_mapping'].keys()))"
```

Expected: list of mark types from existing output files.

- [ ] **Step 7.6: Full suite check**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/ -v --ignore=tests/test_pbi_desktop.py --ignore=tests/test_pbi_e2e_open.py 2>&1 | tail -10
```

Expected: All pre-existing tests pass.

- [ ] **Step 7.7: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/visual_agent.py tests/test_visual_agent.py samples/ docs/visual_conversion.md && git commit -m "feat: add write_registry(), regenerate_visual_conversion_md(), wire __main__"
```

---

## Phase 2 — Provenance + Registry Lookups

---

### Task 8: Add _provenance fields to generator.py

**Files:**
- Modify: `tab_to_pbi/generator.py` — `_write_visual()` at line ~1106
- Modify: `tests/test_visual_agent.py`

- [ ] **Step 8.1: Append failing test**

```python
def test_visual_json_contains_provenance(tmp_path):
    from tab_to_pbi.generator import _write_visual
    visual_info = {
        "name": "SheetA", "page_name": "SheetA", "mark_type": "Bar",
        "table": "orders", "row_fields": [], "col_fields": [],
        "show_data_labels": False, "sorts": [], "visual_format": {},
        "col_formats": {}, "filters": [], "color_fields": [], "title": None,
        "_source_workbook_stem": "my_workbook",
        "_source_visual_index": 1,
    }
    visual_dir = tmp_path / "visual_1"
    visual_dir.mkdir()
    _write_visual(visual_dir, visual_info)
    result = json.loads((visual_dir / "visual.json").read_text())
    prov = result.get("_provenance", {})
    assert prov["source_sheet_name"] == "SheetA"
    assert prov["source_workbook_stem"] == "my_workbook"
    assert prov["source_visual_index"] == 1
```

- [ ] **Step 8.2: Run to verify failure**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py::test_visual_json_contains_provenance -v
```

Expected: FAIL — no `_provenance` key in output.

- [ ] **Step 8.3: Add _provenance to _write_visual() in generator.py**

In `tab_to_pbi/generator.py`, in `_write_visual()` just before `(visual_dir / "visual.json").write_text(...)`:

```python
    # Add provenance for visual_agent.py pairing (stripped before PBIR validation)
    if visual_info.get("_source_workbook_stem") or visual_info.get("name"):
        container["_provenance"] = {
            "source_sheet_name": visual_info.get("page_name") or visual_info.get("name", ""),
            "source_workbook_stem": visual_info.get("_source_workbook_stem", ""),
            "source_visual_index": visual_info.get("_source_visual_index", 0),
        }

    (visual_dir / "visual.json").write_text(json.dumps(container, indent=2))
```

- [ ] **Step 8.4: Pass provenance through transformer.py**

In `tab_to_pbi/transformer.py`, in `_process_sheets()`, when appending to `visuals`, add two fields to each visual dict:

Find the line where `visuals.append(...)` is called (around line 510+). The visual dict already has `name`, `page_name` etc. Add:

```python
        visual_dict = {
            # ... existing fields ...
            "_source_workbook_stem": workbook_name,
            "_source_visual_index": len(visuals) + 1,
        }
        visuals.append(visual_dict)
```

Check `_process_sheets` signature — it already accepts `workbook_name: str = ""`. The caller in `main.py` passes `workbook_name=input_path.stem`. Verify that and pass it through.

- [ ] **Step 8.5: Run tests**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/ -v --ignore=tests/test_pbi_desktop.py --ignore=tests/test_pbi_e2e_open.py 2>&1 | tail -10
```

Expected: All tests PASS including the new provenance test.

- [ ] **Step 8.6: Verify provenance appears in a real run**

```bash
cd C:/vibe_coding/tabToPbi && uv run python -m tab_to_pbi.main input/daatabricks.twb
```

Then:
```bash
cd C:/vibe_coding/tabToPbi && uv run python -c "import json; v=json.load(open('output/daatabricks.Report/definition/pages/ReportSection1/visuals/visual_1/visual.json')); print(v.get('_provenance'))"
```

Expected: `{'source_sheet_name': '...', 'source_workbook_stem': 'daatabricks', 'source_visual_index': 1}`

- [ ] **Step 8.7: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/generator.py tab_to_pbi/transformer.py tests/test_visual_agent.py && git commit -m "feat: add _provenance fields to visual.json for reliable agent pairing"
```

---

### Task 9: visual_mapper.py — thin registry reader

**Files:**
- Create: `tab_to_pbi/visual_mapper.py`
- Create: `tests/test_visual_mapper.py`

- [ ] **Step 9.1: Write failing tests**

Create `tests/test_visual_mapper.py`:

```python
"""Tests for visual_mapper.py — thin runtime registry reader."""
import json
import tempfile
from pathlib import Path
import pytest
import tab_to_pbi.visual_mapper as mapper


def _write_registry(tmp: Path, registry: dict) -> Path:
    (tmp / "samples").mkdir(exist_ok=True)
    p = tmp / "samples" / "visual_mappings.json"
    p.write_text(json.dumps(registry))
    return p


def _minimal_registry():
    return {
        "mark_type_mapping": {
            "Bar": {"pbi_visual_type": "barChart", "status": "validated", "source": {}},
            "CrossTab": {"pbi_visual_type": "pivotTable", "status": "validated", "source": {}},
        },
        "visual_types": {
            "pivotTable": {
                "objects": {
                    "valuesOnRow": {
                        "trigger": "crosstab_measures_non_empty AND row_fields_empty",
                        "pbi_json": {"values": [{"properties": {"valuesOnRow": {"expr": {"Literal": {"Value": "true"}}}}}]},
                        "status": "validated",
                    },
                    "subTotals": {
                        "trigger": "always",
                        "pbi_json": {"subTotals": [{"properties": {
                            "rowSubtotals": {"expr": {"Literal": {"Value": "false"}}},
                            "columnSubtotals": {"expr": {"Literal": {"Value": "false"}}},
                        }}]},
                        "status": "validated",
                    },
                }
            },
            "barChart": {
                "objects": {
                    "labels": {
                        "trigger": "show_data_labels == true",
                        "pbi_json": {"labels": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}]},
                        "status": "validated",
                    }
                }
            },
        },
        "property_mappings": {},
    }


def test_resolve_visual_type_returns_pbi_type(tmp_path):
    reg_path = _write_registry(tmp_path, _minimal_registry())
    mapper.load_registry(registry_path=reg_path)
    assert mapper.resolve_visual_type("Bar") == "barChart"
    assert mapper.resolve_visual_type("CrossTab") == "pivotTable"


def test_resolve_visual_type_returns_none_for_unknown(tmp_path):
    reg_path = _write_registry(tmp_path, _minimal_registry())
    mapper.load_registry(registry_path=reg_path)
    assert mapper.resolve_visual_type("UnknownMark") is None


def test_resolve_visual_type_returns_none_when_registry_absent():
    mapper.load_registry(registry_path=Path("nonexistent/path.json"))
    assert mapper.resolve_visual_type("Bar") is None


def test_resolve_object_fragments_labels_when_show_data_labels(tmp_path):
    reg_path = _write_registry(tmp_path, _minimal_registry())
    mapper.load_registry(registry_path=reg_path)
    frags = mapper.resolve_object_fragments("barChart", {"show_data_labels": True})
    assert "labels" in frags


def test_resolve_object_fragments_no_labels_when_not_set(tmp_path):
    reg_path = _write_registry(tmp_path, _minimal_registry())
    mapper.load_registry(registry_path=reg_path)
    frags = mapper.resolve_object_fragments("barChart", {"show_data_labels": False})
    assert "labels" not in frags


def test_resolve_object_fragments_pivot_valuesOnRow_trigger(tmp_path):
    reg_path = _write_registry(tmp_path, _minimal_registry())
    mapper.load_registry(registry_path=reg_path)
    frags = mapper.resolve_object_fragments(
        "pivotTable",
        {"crosstab_measures": [{"name": "x"}], "row_fields": []},
    )
    assert "values" in frags
    assert "subTotals" in frags


def test_resolve_object_fragments_pivot_no_valuesOnRow_when_row_fields_present(tmp_path):
    reg_path = _write_registry(tmp_path, _minimal_registry())
    mapper.load_registry(registry_path=reg_path)
    frags = mapper.resolve_object_fragments(
        "pivotTable",
        {"crosstab_measures": [{"name": "x"}], "row_fields": [{"name": "region"}]},
    )
    assert "values" not in frags


def test_resolve_object_fragments_returns_empty_dict_when_no_registry(tmp_path):
    mapper.load_registry(registry_path=Path("nonexistent/path.json"))
    frags = mapper.resolve_object_fragments("barChart", {"show_data_labels": True})
    assert frags == {}
```

- [ ] **Step 9.2: Run to verify failures**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_mapper.py -v
```

Expected: `ModuleNotFoundError: No module named 'tab_to_pbi.visual_mapper'`

- [ ] **Step 9.3: Create tab_to_pbi/visual_mapper.py**

```python
"""Thin runtime reader for visual_mappings.json registry.

Read-only. No Claude calls. No visual assembly.
Called by generator.py for object fragment lookups.
"""
import json
from pathlib import Path

_DEFAULT_REGISTRY = Path("samples/visual_mappings.json")
_registry: dict = {}


def load_registry(registry_path: Path | None = None) -> None:
    """Load registry into module-level cache. Call once from main.py."""
    global _registry
    path = registry_path or _DEFAULT_REGISTRY
    if path.exists():
        _registry = json.loads(path.read_text())
    else:
        _registry = {}


def resolve_visual_type(mark_type: str) -> str | None:
    """Return PBI visual type for a Tableau mark type. None if absent or registry empty."""
    entry = _registry.get("mark_type_mapping", {}).get(mark_type)
    return entry.get("pbi_visual_type") if entry else None


def resolve_object_fragments(visual_type: str, visual_info: dict) -> dict:
    """Return merged pbi_json fragments applicable to this visual.

    Evaluates trigger conditions against visual_info.
    Returns empty dict if registry is empty or visual_type absent.
    """
    if not _registry:
        return {}
    result: dict = {}
    vt_entry = _registry.get("visual_types", {}).get(visual_type, {})
    for obj_entry in vt_entry.get("objects", {}).values():
        if _eval_trigger(obj_entry.get("trigger", "always"), visual_info):
            result.update(obj_entry.get("pbi_json", {}))
    for prop_entry in _registry.get("property_mappings", {}).values():
        applicable = prop_entry.get("applicable_visual_types", [])
        excluded = prop_entry.get("excluded_visual_types", [])
        if visual_type in excluded:
            continue
        if "*" in applicable or visual_type in applicable:
            if _eval_trigger(prop_entry.get("trigger", "always"), visual_info):
                result.update(prop_entry.get("pbi_json", {}))
    return result


def _eval_trigger(trigger: str, visual_info: dict) -> bool:
    if trigger == "always":
        return True
    if trigger == "show_data_labels == true":
        return bool(visual_info.get("show_data_labels"))
    if trigger == "crosstab_measures_non_empty AND row_fields_empty":
        return bool(visual_info.get("crosstab_measures")) and not visual_info.get("row_fields")
    return False
```

- [ ] **Step 9.4: Run tests**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_mapper.py -v
```

Expected: All tests PASS.

- [ ] **Step 9.5: Full suite check**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/ -v --ignore=tests/test_pbi_desktop.py --ignore=tests/test_pbi_e2e_open.py 2>&1 | tail -10
```

Expected: All pre-existing tests still pass.

- [ ] **Step 9.6: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/visual_mapper.py tests/test_visual_mapper.py && git commit -m "feat: add visual_mapper.py thin registry reader with trigger evaluation"
```

---

### Task 10: generator.py consults registry for object fragments

**Files:**
- Modify: `tab_to_pbi/generator.py` — `_build_objects()` at line ~1179
- Modify: `tests/test_visual_mapper.py`

- [ ] **Step 10.1: Append failing test**

```python
def test_build_objects_uses_registry_when_loaded(tmp_path):
    import tab_to_pbi.visual_mapper as mapper
    from tab_to_pbi.generator import _build_objects
    reg = _minimal_registry()
    reg_path = _write_registry(tmp_path, reg)
    mapper.load_registry(registry_path=reg_path)
    visual_info = {"show_data_labels": True, "visual_format": {}, "crosstab_measures": [], "row_fields": []}
    result = _build_objects(visual_info, "barChart")
    assert "labels" in result
    mapper.load_registry(registry_path=Path("nonexistent.json"))  # reset
```

- [ ] **Step 10.2: Run to verify failure**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_mapper.py::test_build_objects_uses_registry_when_loaded -v
```

Expected: PASS already — `_build_objects` already handles labels. Now verify it uses registry path:

This test verifies that when the registry IS loaded, `_build_objects` returns the same result as before. Since existing logic handles `labels` hardcoded, this test already passes. The real change is to **add registry lookup as the primary path**. Modify the test to verify a registry-only scenario:

```python
def test_build_objects_falls_back_to_hardcode_when_no_registry(tmp_path):
    import tab_to_pbi.visual_mapper as mapper
    from tab_to_pbi.generator import _build_objects
    mapper.load_registry(registry_path=Path("nonexistent.json"))
    visual_info = {"show_data_labels": True, "visual_format": {}, "crosstab_measures": [], "row_fields": []}
    result = _build_objects(visual_info, "barChart")
    # Hardcoded fallback should still produce labels
    assert "labels" in result
```

- [ ] **Step 10.3: Modify _build_objects() in generator.py**

In `tab_to_pbi/generator.py`, at the top of `_build_objects()`, add registry consultation before the hardcoded logic:

```python
def _build_objects(visual_info: dict, visual_type: str) -> dict:
    """Build the visual.objects dict. Consults registry first; falls back to hardcoded logic."""
    def lit(v: str) -> dict:
        return {"expr": {"Literal": {"Value": v}}}

    # --- Registry path (P2+) ---
    try:
        from tab_to_pbi import visual_mapper
        registry_frags = visual_mapper.resolve_object_fragments(visual_type, visual_info)
        if registry_frags:
            # Registry present and has entries — merge with any axis formatting from hardcode
            objects = dict(registry_frags)
            # Always run the axis/formatting section regardless (not in registry yet)
            fmt = visual_info.get("visual_format", {})
            if fmt and visual_type in _AXIS_VISUAL_TYPES:
                _apply_axis_format(objects, fmt, lit)
            return objects
    except Exception:
        pass

    # --- Hardcoded fallback (registry absent or empty) ---
    objects: dict = {}
    if visual_info.get("show_data_labels") and visual_type not in ("tableEx", "pivotTable"):
        objects["labels"] = [{"properties": {"show": lit("true")}}]
    if visual_type == "pivotTable" and visual_info.get("crosstab_measures") and not visual_info.get("row_fields"):
        objects["values"] = [{"properties": {"valuesOnRow": lit("true")}}]
        objects["subTotals"] = [{"properties": {
            "rowSubtotals": lit("false"),
            "columnSubtotals": lit("false"),
        }}]
    fmt = visual_info.get("visual_format", {})
    if not fmt or visual_type not in _AXIS_VISUAL_TYPES:
        return objects
    _apply_axis_format(objects, fmt, lit)
    return objects
```

Extract the axis formatting block into `_apply_axis_format(objects, fmt, lit)` (refactor the existing inline code into a helper). The existing `_build_objects` body below the `if not fmt...` line becomes `_apply_axis_format`.

Read `generator.py` lines 1179–1250 to find the exact axis formatting code before refactoring it.

- [ ] **Step 10.4: Run tests**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/ -v --ignore=tests/test_pbi_desktop.py --ignore=tests/test_pbi_e2e_open.py 2>&1 | tail -10
```

Expected: All tests PASS. No regression — fallback path preserves existing behaviour.

- [ ] **Step 10.5: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/generator.py tests/test_visual_mapper.py && git commit -m "feat: generator._build_objects() consults registry with hardcoded fallback"
```

---

### Task 11: main.py loads registry at startup

**Files:**
- Modify: `tab_to_pbi/main.py`

- [ ] **Step 11.1: Add load_registry() call**

In `tab_to_pbi/main.py`, after existing imports add:

```python
from tab_to_pbi.visual_mapper import load_registry
```

At the start of `main()` (before any parsing), add:

```python
    load_registry()
```

- [ ] **Step 11.2: Full suite check**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/ -v --ignore=tests/test_pbi_desktop.py --ignore=tests/test_pbi_e2e_open.py 2>&1 | tail -10
```

Expected: All tests PASS.

- [ ] **Step 11.3: Run end-to-end**

```bash
cd C:/vibe_coding/tabToPbi && uv run python -m tab_to_pbi.main input/daatabricks.twb
```

Expected: Pipeline runs with 0 errors. If `samples/visual_mappings.json` exists, registry is loaded silently. If absent, fallback constants are used — same output as before.

- [ ] **Step 11.4: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/main.py && git commit -m "feat: load visual_mappings.json registry at pipeline startup"
```

---

## Phase 3 — Advisory Suggestion Mode

---

### Task 12: Runtime Claude fallback → suggestion artifact

**Files:**
- Modify: `tab_to_pbi/visual_mapper.py`
- Modify: `tests/test_visual_mapper.py`

- [ ] **Step 12.1: Append failing tests**

```python
def test_suggest_unknown_property_writes_suggestion_file(tmp_path):
    from unittest.mock import patch, MagicMock
    import tab_to_pbi.visual_mapper as mapper
    reg_path = _write_registry(tmp_path, _minimal_registry())
    mapper.load_registry(registry_path=reg_path)

    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=json.dumps({
        "pbi_json": {"customProp": [{"properties": {}}]},
        "confidence": 0.85,
    }))]
    suggestion_path = tmp_path / "test_wb.visual_mapping_suggestions.json"
    with patch("tab_to_pbi.visual_mapper._call_claude", return_value=mock_resp):
        mapper.suggest_unknown_property(
            visual_type="barChart",
            tableau_property="custom_format",
            visual_info={},
            workbook_stem="test_wb",
            output_dir=tmp_path,
        )
    assert suggestion_path.exists()
    data = json.loads(suggestion_path.read_text())
    assert len(data["suggestions"]) == 1
    assert data["suggestions"][0]["score"] == 0.85
    assert data["suggestions"][0]["status"] == "pending_review"


def test_suggest_low_confidence_still_writes_but_flagged(tmp_path):
    from unittest.mock import patch, MagicMock
    import tab_to_pbi.visual_mapper as mapper
    reg_path = _write_registry(tmp_path, _minimal_registry())
    mapper.load_registry(registry_path=reg_path)
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=json.dumps({
        "pbi_json": {"lowConfProp": []},
        "confidence": 0.3,
    }))]
    suggestion_path = tmp_path / "test_wb.visual_mapping_suggestions.json"
    with patch("tab_to_pbi.visual_mapper._call_claude", return_value=mock_resp):
        mapper.suggest_unknown_property(
            visual_type="barChart",
            tableau_property="low_conf_prop",
            visual_info={},
            workbook_stem="test_wb",
            output_dir=tmp_path,
        )
    data = json.loads(suggestion_path.read_text())
    assert data["suggestions"][0]["score"] == 0.3
    assert data["suggestions"][0]["status"] == "pending_review"
```

- [ ] **Step 12.2: Run to verify failures**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_mapper.py -v -k "test_suggest"
```

Expected: FAIL — `suggest_unknown_property` not defined.

- [ ] **Step 12.3: Implement suggest_unknown_property() in visual_mapper.py**

Add to `tab_to_pbi/visual_mapper.py`:

```python
import os
from datetime import datetime, timezone
import anthropic

_CLAUDE_MODEL = "claude-opus-4-7"


def _call_claude(prompt: str) -> object:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )


def suggest_unknown_property(
    visual_type: str,
    tableau_property: str,
    visual_info: dict,
    workbook_stem: str,
    output_dir: Path | None = None,
) -> dict | None:
    """Call Claude for an unknown property. Writes result to output/<stem>.visual_mapping_suggestions.json.

    Never writes to samples/visual_mappings.json. Returns suggestion dict or None on failure.
    """
    out = output_dir or Path("output")
    suggestion_path = out / f"{workbook_stem}.visual_mapping_suggestions.json"

    # Find nearest sample for grounding
    sample = next(
        (v for v in _registry.get("visual_types", {}).values()
         if v.get("status") == "validated"),
        {},
    )
    prompt = (
        f"Map Tableau property '{tableau_property}' to PBI PBIR objects JSON for visual type '{visual_type}'.\n"
        f"PBI objects structure: {{\"key\": [{{\"properties\": {{\"prop\": {{\"expr\": {{\"Literal\": {{\"Value\": \"val\"}}}}}}}}}}]}}\n"
        f"Nearest validated sample objects: {json.dumps(sample.get('objects', {}))}\n"
        f"Return JSON with keys: pbi_json (dict), confidence (float 0-1). No other text."
    )
    try:
        response = _call_claude(prompt)
        data = json.loads(response.content[0].text.strip())
        suggestion = {
            "visual_type": visual_type,
            "tableau_property": tableau_property,
            "pbi_json": data.get("pbi_json", {}),
            "score": float(data.get("confidence", 0.5)),
            "status": "pending_review",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        print(f"  suggestion failed for {tableau_property}: {exc}")
        return None

    # Append to suggestion file (create if absent)
    existing: dict = {"workbook": workbook_stem, "suggestions": []}
    if suggestion_path.exists():
        existing = json.loads(suggestion_path.read_text())
    existing["suggestions"].append(suggestion)
    suggestion_path.write_text(json.dumps(existing, indent=2))
    return suggestion
```

- [ ] **Step 12.4: Run tests**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_mapper.py -v
```

Expected: All tests PASS.

- [ ] **Step 12.5: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/visual_mapper.py tests/test_visual_mapper.py && git commit -m "feat: add suggest_unknown_property() advisory suggestion mode to visual_mapper"
```

---

### Task 13: migration_report.json gains visual_mapping_suggestions section

**Files:**
- Modify: `tab_to_pbi/main.py`

- [ ] **Step 13.1: Add visual_mapping_suggestions to migration report**

In `tab_to_pbi/main.py`, in the section that builds `report_data`, add:

```python
    # Collect any suggestion files written during this run
    suggestion_file = output_dir / f"{input_path.stem}.visual_mapping_suggestions.json"
    if suggestion_file.exists():
        import json as _json
        suggestions_data = _json.loads(suggestion_file.read_text())
        report_data["visual_mapping_suggestions"] = {
            s["tableau_property"]: {
                "visual_type": s["visual_type"],
                "score": s["score"],
                "review_file": str(suggestion_file),
            }
            for s in suggestions_data.get("suggestions", [])
        }
```

- [ ] **Step 13.2: Full suite check**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/ -v --ignore=tests/test_pbi_desktop.py --ignore=tests/test_pbi_e2e_open.py 2>&1 | tail -10
```

Expected: All tests PASS.

- [ ] **Step 13.3: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/main.py && git commit -m "feat: add visual_mapping_suggestions section to migration_report.json"
```

---

### Task 14: visual_agent.py --ingest-suggestions flag

**Files:**
- Modify: `tab_to_pbi/visual_agent.py`
- Modify: `tests/test_visual_agent.py`

- [ ] **Step 14.1: Append failing test**

```python
from tab_to_pbi.visual_agent import ingest_suggestions


def test_ingest_suggestions_promotes_pending_review():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "samples").mkdir()
        # Write an existing registry
        registry = {
            "version": "1.0.0", "generated_at": "t",
            "mark_type_mapping": {}, "automatic_inference_rules": [],
            "visual_types": {"barChart": {"objects": {}}},
            "property_mappings": {},
        }
        reg_path = tmp / "samples" / "visual_mappings.json"
        reg_path.write_text(json.dumps(registry))
        # Write suggestion file
        suggestion_file = tmp / "output" / "test_wb.visual_mapping_suggestions.json"
        (tmp / "output").mkdir()
        suggestion_file.write_text(json.dumps({
            "workbook": "test_wb",
            "suggestions": [{
                "visual_type": "barChart",
                "tableau_property": "custom_prop",
                "pbi_json": {"customProp": [{"properties": {}}]},
                "score": 0.9,
                "status": "pending_review",
                "generated_at": "t",
            }],
        }))
        ingest_suggestions(
            suggestion_paths=[suggestion_file],
            registry_path=reg_path,
        )
        result = json.loads(reg_path.read_text())
        assert "customProp" in result["visual_types"]["barChart"]["objects"]
        assert result["visual_types"]["barChart"]["objects"]["customProp"]["status"] == "inferred"
```

- [ ] **Step 14.2: Run to verify failure**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py::test_ingest_suggestions_promotes_pending_review -v
```

Expected: FAIL.

- [ ] **Step 14.3: Implement ingest_suggestions() in visual_agent.py**

Add to `tab_to_pbi/visual_agent.py`:

```python
def ingest_suggestions(
    suggestion_paths: list[Path] | None = None,
    registry_path: Path | None = None,
) -> None:
    """Promote pending_review suggestions into the registry as 'inferred'.

    Called via: uv run tab_to_pbi/visual_agent.py --ingest-suggestions
    Only visual_agent.py writes the registry — never the pipeline.
    """
    reg_path = registry_path or _REGISTRY_FILE
    if not reg_path.exists():
        print("  no registry found; run visual_agent.py first")
        return
    registry = json.loads(reg_path.read_text())

    paths = suggestion_paths or list(_OUTPUT_DIR.glob("*.visual_mapping_suggestions.json"))
    ingested = 0
    for path in paths:
        data = json.loads(path.read_text())
        for s in data.get("suggestions", []):
            if s.get("status") != "pending_review":
                continue
            vtype = s["visual_type"]
            prop = s["tableau_property"]
            pbi_json = s.get("pbi_json", {})
            for obj_key, obj_val in pbi_json.items():
                registry.setdefault("visual_types", {}).setdefault(vtype, {}).setdefault("objects", {})[obj_key] = {
                    "pbi_json": {obj_key: obj_val},
                    "trigger": "always",
                    "status": "inferred",
                    "score": s.get("score", 0.5),
                    "source": {"workbook": data.get("workbook", ""), "sheet": ""},
                    "schema_validated": False,
                }
            ingested += 1
    write_registry(registry, registry_path=reg_path)
    print(f"  ingested {ingested} suggestions into registry")
```

Update `if __name__ == "__main__":` to handle the flag:

```python
if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()

    if "--ingest-suggestions" in sys.argv:
        print("visual_agent: ingesting suggestions...")
        ingest_suggestions()
        print("visual_agent: done.")
    else:
        # ... existing main flow ...
```

- [ ] **Step 14.4: Run tests**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/test_visual_agent.py -v
```

Expected: All tests PASS.

- [ ] **Step 14.5: Full suite check**

```bash
cd C:/vibe_coding/tabToPbi && uv run pytest tests/ -v --ignore=tests/test_pbi_desktop.py --ignore=tests/test_pbi_e2e_open.py 2>&1 | tail -10
```

Expected: All tests PASS.

- [ ] **Step 14.6: Commit**

```bash
cd C:/vibe_coding/tabToPbi && git add tab_to_pbi/visual_agent.py tests/test_visual_agent.py && git commit -m "feat: add ingest_suggestions() and --ingest-suggestions flag to visual_agent"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task |
|-----------------|------|
| `samples/validation_manifest.yaml` user-maintained config | Task 1 |
| `samples/baselines/<type>_minimal.json` curated baselines | Task 2 |
| `visual_agent.py` sole writer of registry | Tasks 3–7, 14 |
| `load_manifest()` + validated lookup | Task 3 |
| `scan_output_pairs()` using provenance then name fallback | Tasks 3, 8 |
| `extract_mark_type_mapping()` — never downgrades validated | Task 4 |
| `extract_query_roles()` from known templates | Task 4 |
| `extract_objects()` with baseline diff + schema validation | Task 5 |
| `fill_gaps_with_claude()` for inferred visual types | Task 6 |
| `write_registry()` — no-downgrade merge on re-run | Task 7 |
| `regenerate_visual_conversion_md()` with confidence badges | Task 7 |
| `__main__` wiring with end-to-end run | Task 7 |
| `_provenance` fields added to `visual.json` | Task 8 |
| `visual_mapper.py` thin reader — `load_registry` + `resolve_visual_type` + `resolve_object_fragments` | Task 9 |
| `_build_objects()` consults registry, falls back to hardcode | Task 10 |
| `main.py` loads registry at startup | Task 11 |
| Runtime Claude fallback → suggestion artifact (never registry) | Task 12 |
| `migration_report.json` gains `visual_mapping_suggestions` | Task 13 |
| `--ingest-suggestions` flag promotes to registry | Task 14 |
| Hardcoded `MARK_TO_VISUAL`/`_VISUAL_ROLES`/`_build_objects` kept as fallbacks | Tasks 9, 10 |
| Registry covers only layers 2+3 (not semantic normalization) | Architecture (no task changes _infer_mark_type) |

### Placeholder scan

No TBDs. All code steps are complete. Task 10 has one inline note: "Read generator.py lines 1179–1250 to find exact axis formatting code." This is a read step, not a placeholder — the implementer must read the current code before refactoring it.

### Type consistency

- `load_manifest()` returns `dict[str, dict]` → passed as `validated` to `scan_output_pairs(validated, ...)` ✓
- `scan_output_pairs()` returns `list[dict]` → passed to `extract_*` functions ✓
- `extract_mark_type_mapping()` returns `dict` → assigned to `registry["mark_type_mapping"]` ✓
- `write_registry(registry, registry_path=...)` → `registry_path` is `Path | None` ✓
- `visual_mapper.load_registry(registry_path=...)` → `registry_path` is `Path | None` ✓
- `suggest_unknown_property(..., output_dir=Path|None)` → consistent throughout ✓
- `ingest_suggestions(suggestion_paths=list[Path]|None, registry_path=Path|None)` ✓
