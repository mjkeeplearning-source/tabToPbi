# Dashboard Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate Tableau dashboards to PBI pages — each dashboard becomes a new PBI report page containing repositioned chart visuals, slicer visuals for filter zones, and textbox visuals for text/title zones.

**Architecture:** New `tab_to_pbi/dashboard.py` module with three public functions: `parse_dashboards_from_path()`, `transform_dashboards()`, and `write_dashboard_pages()`. Zero changes to existing parser/transformer/generator/translator. `main.py` gets a small addition to wire the three functions in after the existing pipeline.

**Tech Stack:** Python 3.11+, xml.etree.ElementTree (stdlib), json (stdlib), pathlib (stdlib), zipfile (stdlib). Imports `MARK_TO_VISUAL`, `_VISUAL_ROLES`, `_make_projection` from existing `generator.py`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tab_to_pbi/dashboard.py` | Create | All dashboard logic: parse, transform, write |
| `tests/test_dashboard.py` | Create | Unit tests for all dashboard functions |
| `tab_to_pbi/main.py` | Modify (add ~8 lines) | Wire dashboard pipeline after existing generate() call |

---

## Task 1: Create dashboard.py scaffold + parse_dashboards()

Parse `<dashboards>` XML into a list of dashboard dicts with name, size, title, and flat zone list.

**Files:**
- Create: `tab_to_pbi/dashboard.py`
- Create: `tests/test_dashboard.py`

- [ ] **Step 1.1: Write failing tests**

```python
# tests/test_dashboard.py
import xml.etree.ElementTree as ET
from pathlib import Path
from tab_to_pbi.dashboard import parse_dashboards, parse_dashboards_from_path

TWB = Path("input/Superstore.twb")


def test_parse_dashboards_count():
    root = ET.parse(TWB).getroot()
    dashboards = parse_dashboards(root)
    assert len(dashboards) == 6


def test_parse_dashboard_names():
    root = ET.parse(TWB).getroot()
    names = [d["name"] for d in parse_dashboards(root)]
    assert "Overview" in names
    assert "Shipping" in names
    assert "Customers" in names


def test_parse_dashboard_size():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    assert shipping["width"] == 1000
    assert shipping["height"] == 620


def test_parse_dashboard_title():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    assert shipping["title"] == "On-Time Shipment Trends"


def test_parse_dashboards_from_path():
    dashboards = parse_dashboards_from_path(TWB)
    assert len(dashboards) == 6
```

- [ ] **Step 1.2: Run tests to verify they fail**

```
uv run pytest tests/test_dashboard.py -v
```

Expected: `ModuleNotFoundError: No module named 'tab_to_pbi.dashboard'`

- [ ] **Step 1.3: Create `tab_to_pbi/dashboard.py` with scaffold and parse_dashboards()**

```python
"""Tableau dashboard zones → PBI dashboard pages."""

import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from tab_to_pbi.generator import MARK_TO_VISUAL, _VISUAL_ROLES, _make_projection

_SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report"
_PBI_W = 1280
_PBI_H = 720

_SLICER_MODE_MAP = {
    "dropdown": "Dropdown",
    "slider": "Between",
    "compact": "Dropdown",
    "type_in": "Dropdown",
    "radiolist": "Basic",
    "checkdropdown": "Dropdown",
}


def parse_dashboards_from_path(path: Path) -> list[dict]:
    """Parse dashboards from a .twb or .twbx file."""
    if path.suffix.lower() == ".twbx":
        with zipfile.ZipFile(path) as zf:
            twb_name = next(n for n in zf.namelist() if n.endswith(".twb"))
            with zf.open(twb_name) as f:
                root = ET.parse(f).getroot()
    else:
        root = ET.parse(path).getroot()
    return parse_dashboards(root)


def parse_dashboards(root: ET.Element) -> list[dict]:
    """Extract dashboard definitions from workbook XML root."""
    dashboards = []
    for dash in root.findall("./dashboards/dashboard"):
        name = dash.get("name", "")
        if not name:
            continue
        size = dash.find("size")
        width = int(size.get("minwidth", "1000")) if size is not None else 1000
        height = int(size.get("minheight", "620")) if size is not None else 620
        title_run = dash.find("./layout-options/title/formatted-text/run")
        title = (title_run.text or "").strip() if title_run is not None else name

        zones_el = dash.find("zones")
        zones = _flatten_zones(zones_el, title) if zones_el is not None else []

        dashboards.append({
            "name": name,
            "width": width,
            "height": height,
            "title": title,
            "zones": zones,
        })
    return dashboards


def _flatten_zones(el: ET.Element, dashboard_title: str) -> list[dict]:
    """Recursively walk zone tree, collecting leaf content zones with absolute coords."""
    results = []
    for zone in el.findall("zone"):
        type_v2 = zone.get("type-v2", "")
        name = zone.get("name", "")

        if type_v2 in ("layout-flow", "layout-basic"):
            results.extend(_flatten_zones(zone, dashboard_title))
        elif not type_v2 and name:
            results.append({
                "zone_type": "sheet",
                "name": name,
                "x": int(zone.get("x", 0)),
                "y": int(zone.get("y", 0)),
                "w": int(zone.get("w", 0)),
                "h": int(zone.get("h", 0)),
            })
        elif type_v2 == "filter":
            fz = _extract_filter_zone(zone)
            if fz:
                results.append(fz)
        elif type_v2 == "title":
            results.append({
                "zone_type": "title",
                "text": dashboard_title,
                "x": int(zone.get("x", 0)),
                "y": int(zone.get("y", 0)),
                "w": int(zone.get("w", 0)),
                "h": int(zone.get("h", 0)),
            })
        elif type_v2 == "text":
            tz = _extract_text_zone(zone)
            if tz:
                results.append(tz)
        # paramctrl, color, empty → skip silently
    return results


def _extract_filter_zone(zone: ET.Element) -> dict | None:
    """Extract filter zone dict from a type-v2='filter' element."""
    param = zone.get("param", "")
    source_sheet = zone.get("name", "")
    if not param:
        return None
    if "].[" in param:
        ds_part, field_part = param.split("].[", 1)
        datasource_id = ds_part.lstrip("[")
        field_ref = field_part.rstrip("]")
    else:
        datasource_id = ""
        field_ref = param.strip("[]")

    segments = field_ref.split(":", 2)
    param_field = segments[1] if len(segments) == 3 else field_ref

    return {
        "zone_type": "filter",
        "name": source_sheet,
        "param_field": param_field,
        "param_datasource_id": datasource_id,
        "mode": zone.get("mode", ""),
        "x": int(zone.get("x", 0)),
        "y": int(zone.get("y", 0)),
        "w": int(zone.get("w", 0)),
        "h": int(zone.get("h", 0)),
    }


def _extract_text_zone(zone: ET.Element) -> dict | None:
    """Extract text zone dict from a type-v2='text' element."""
    run = zone.find("./formatted-text/run")
    text = (run.text or "").strip() if run is not None else ""
    if not text:
        return None
    return {
        "zone_type": "text",
        "text": text,
        "x": int(zone.get("x", 0)),
        "y": int(zone.get("y", 0)),
        "w": int(zone.get("w", 0)),
        "h": int(zone.get("h", 0)),
    }


# Stubs — implemented in later tasks
def transform_dashboards(dashboards: list[dict], workbook: dict, transformed: dict) -> list[dict]:
    return []


def write_dashboard_pages(dashboard_pages: list[dict], output_dir: Path, stem: str) -> list[dict]:
    return []
```

- [ ] **Step 1.4: Run tests to verify they pass**

```
uv run pytest tests/test_dashboard.py -v
```

Expected: 5 tests PASS

- [ ] **Step 1.5: Commit**

```
git add tab_to_pbi/dashboard.py tests/test_dashboard.py
git commit -m "feat: add dashboard.py scaffold with parse_dashboards()"
```

---

## Task 2: Zone parsing tests — sheet zones, filter zones, text zones

Verify the correct zone types and coordinates are extracted from Superstore.twb dashboards.

**Files:**
- Modify: `tests/test_dashboard.py` (append new tests)

- [ ] **Step 2.1: Append failing tests to `tests/test_dashboard.py`**

```python
def test_shipping_sheet_zones():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    sheet_zones = [z for z in shipping["zones"] if z["zone_type"] == "sheet"]
    names = {z["name"] for z in sheet_zones}
    assert "ShippingTrend" in names
    assert "ShipSummary" in names
    assert "DaystoShip" in names
    assert len(sheet_zones) == 3


def test_shipping_filter_zones():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    filter_zones = [z for z in shipping["zones"] if z["zone_type"] == "filter"]
    assert len(filter_zones) == 4
    fields = {z["param_field"] for z in filter_zones}
    assert "Region" in fields
    assert "Ship Mode" in fields
    assert "Order Date" in fields


def test_filter_zone_scoped_to_sheet():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    filter_zones = [z for z in shipping["zones"] if z["zone_type"] == "filter"]
    assert all(z["name"] == "ShippingTrend" for z in filter_zones)


def test_filter_zone_mode_mapping_checkdropdown():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    region_filter = next(
        z for z in shipping["zones"]
        if z["zone_type"] == "filter" and z["param_field"] == "Region"
    )
    assert region_filter["mode"] == "checkdropdown"
    assert region_filter["param_datasource_id"] == "federated.10nnk8d1vgmw8q17yu76u06pnbcj"


def test_shipping_title_zone():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    title_zones = [z for z in shipping["zones"] if z["zone_type"] == "title"]
    assert len(title_zones) == 1
    assert title_zones[0]["text"] == "On-Time Shipment Trends"


def test_paramctrl_zones_excluded():
    root = ET.parse(TWB).getroot()
    commission = next(d for d in parse_dashboards(root) if d["name"] == "Commission Model")
    zone_types = {z["zone_type"] for z in commission["zones"]}
    assert "paramctrl" not in zone_types


def test_sheet_zone_has_coordinates():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    trend = next(z for z in shipping["zones"] if z.get("name") == "ShippingTrend")
    assert trend["x"] == 410
    assert trend["y"] == 14915
    assert trend["w"] == 86935
    assert trend["h"] == 32743
```

- [ ] **Step 2.2: Run tests to verify failures**

```
uv run pytest tests/test_dashboard.py -v -k "test_shipping or test_filter or test_paramctrl or test_sheet_zone"
```

Expected: All new tests FAIL (coordinates hardcoded, zones not extracted yet)

- [ ] **Step 2.3: Run full test suite to confirm no regressions**

```
uv run pytest tests/ -v
```

Expected: All pre-existing tests PASS, only new zone tests fail.

- [ ] **Step 2.4: Run tests to verify they now pass**

The zone extraction is already implemented in Task 1's `_flatten_zones`. Run:

```
uv run pytest tests/test_dashboard.py -v
```

Expected: All 12 tests PASS (Task 1 implementation already covers this).

If any fail, cross-check the XML coordinates in `input/Superstore.twb` at lines 6115 and 6124 and adjust the assertions.

- [ ] **Step 2.5: Commit**

```
git add tests/test_dashboard.py
git commit -m "test: add zone parsing tests for dashboard.py"
```

---

## Task 3: transform_dashboards() — coordinate conversion + sheet zones

Scale Tableau 100000-unit coordinates to PBI 1280×720 pixels. For each worksheet zone find the matching visual from the transformed output and build a chart visual dict.

**Files:**
- Modify: `tests/test_dashboard.py` (append)
- Modify: `tab_to_pbi/dashboard.py` (replace `transform_dashboards` stub)

- [ ] **Step 3.1: Append failing tests**

```python
from tab_to_pbi.dashboard import transform_dashboards


def _make_workbook_stub():
    return {
        "datasources": [{
            "name": "federated.abc",
            "columns": [
                {"name": "Region", "source_table": "orders"},
                {"name": "Sales", "source_table": "orders"},
            ],
        }]
    }


def _make_transformed_stub():
    return {
        "visuals": [{
            "name": "Sheet1",
            "page_name": "Sheet1",
            "mark_type": "Bar",
            "table": "orders",
            "row_fields": [{"name": "Region", "is_measure": False, "table": "orders"}],
            "col_fields": [{"name": "Sum Sales", "is_measure": True, "table": "orders"}],
        }]
    }


def test_transform_coordinate_scaling():
    dashboards = [{
        "name": "TestDash",
        "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "sheet", "name": "Sheet1",
            "x": 50000, "y": 50000, "w": 50000, "h": 50000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    assert len(pages) == 1
    v = pages[0]["visuals"][0]
    assert v["x"] == 640     # round(50000/100000 * 1280)
    assert v["y"] == 360     # round(50000/100000 * 720)
    assert v["width"] == 640
    assert v["height"] == 360


def test_transform_sheet_zone_becomes_chart_visual():
    dashboards = [{
        "name": "TestDash",
        "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "sheet", "name": "Sheet1",
            "x": 0, "y": 0, "w": 100000, "h": 100000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    v = pages[0]["visuals"][0]
    assert v["visual_type"] == "chart"
    assert v["source_sheet"] == "Sheet1"
    assert v["mark_type"] == "Bar"
    assert v["table"] == "orders"


def test_transform_unknown_sheet_skipped():
    dashboards = [{
        "name": "TestDash",
        "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "sheet", "name": "NonExistentSheet",
            "x": 0, "y": 0, "w": 50000, "h": 50000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    assert pages[0]["visuals"] == []


def test_transform_page_dimensions():
    dashboards = [{
        "name": "MyDash", "width": 1000, "height": 620, "title": "My Dashboard",
        "zones": [],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    assert pages[0]["page_name"] == "Dashboard_MyDash"
    assert pages[0]["display_name"] == "My Dashboard"
    assert pages[0]["width"] == 1280
    assert pages[0]["height"] == 720
```

- [ ] **Step 3.2: Run to verify failures**

```
uv run pytest tests/test_dashboard.py -v -k "test_transform"
```

Expected: FAIL — `transform_dashboards` returns `[]`

- [ ] **Step 3.3: Replace `transform_dashboards` stub in `dashboard.py`**

Replace the stub `transform_dashboards` function with:

```python
def _scale(tab_val: int, pbi_dim: int) -> int:
    return round((tab_val / 100000) * pbi_dim)


def _resolve_field_entity(datasource_id: str, field_name: str, workbook: dict) -> str:
    """Return PBI table name for a field in a given datasource."""
    for ds in workbook.get("datasources", []):
        if ds["name"] == datasource_id:
            for col in ds.get("columns", []):
                if col["name"] == field_name:
                    return col.get("source_table", "")
    return ""


def _find_visual_for_sheet(sheet_name: str, transformed: dict) -> dict | None:
    """Return first visual dict from transformed output matching the sheet page name."""
    for v in transformed.get("visuals", []):
        if v.get("page_name") == sheet_name or v.get("name") == sheet_name:
            return v
    return None


def transform_dashboards(
    dashboards: list[dict],
    workbook: dict,
    transformed: dict,
) -> list[dict]:
    """Convert dashboard dicts into PBI page dicts with positioned visuals."""
    pages = []
    for dash in dashboards:
        visuals: list[dict] = []
        unsupported: list[str] = []
        visual_idx = 0

        for zone in dash["zones"]:
            visual_id = f"dash_visual_{visual_idx + 1}"
            px = _scale(zone["x"], _PBI_W)
            py = _scale(zone["y"], _PBI_H)
            pw = _scale(zone["w"], _PBI_W)
            ph = _scale(zone["h"], _PBI_H)

            if zone["zone_type"] == "sheet":
                source = _find_visual_for_sheet(zone["name"], transformed)
                if source is None:
                    continue
                visuals.append({
                    "visual_id": visual_id,
                    "visual_type": "chart",
                    "x": px, "y": py, "width": pw, "height": ph,
                    "source_sheet": zone["name"],
                    "mark_type": source["mark_type"],
                    "table": source["table"],
                    "row_fields": source.get("row_fields", []),
                    "col_fields": source.get("col_fields", []),
                })
                visual_idx += 1

            elif zone["zone_type"] == "filter":
                entity = _resolve_field_entity(
                    zone["param_datasource_id"], zone["param_field"], workbook
                )
                if not entity:
                    continue
                visuals.append({
                    "visual_id": visual_id,
                    "visual_type": "slicer",
                    "x": px, "y": py, "width": pw, "height": ph,
                    "field_entity": entity,
                    "field_property": zone["param_field"],
                    "slicer_mode": _SLICER_MODE_MAP.get(zone["mode"], "Basic"),
                    "scoped_to_sheet": zone["name"],
                })
                visual_idx += 1

            elif zone["zone_type"] in ("text", "title"):
                visuals.append({
                    "visual_id": visual_id,
                    "visual_type": "textbox",
                    "x": px, "y": py, "width": pw, "height": ph,
                    "text": zone["text"],
                })
                visual_idx += 1

        chart_visuals = [v for v in visuals if v["visual_type"] == "chart"]
        slicer_visuals = [v for v in visuals if v["visual_type"] == "slicer"]
        interactions = [
            {"source": s["visual_id"], "target": c["visual_id"], "type": "NoFilter"}
            for s in slicer_visuals
            for c in chart_visuals
            if c["source_sheet"] != s["scoped_to_sheet"]
        ]

        pages.append({
            "page_name": f"Dashboard_{dash['name'].replace(' ', '_')}",
            "display_name": dash["name"],
            "width": _PBI_W,
            "height": _PBI_H,
            "visuals": visuals,
            "visual_interactions": interactions,
            "unsupported": unsupported,
        })
    return pages
```

- [ ] **Step 3.4: Run tests**

```
uv run pytest tests/test_dashboard.py -v -k "test_transform"
```

Expected: All transform tests PASS

- [ ] **Step 3.5: Full suite check**

```
uv run pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 3.6: Commit**

```
git add tab_to_pbi/dashboard.py tests/test_dashboard.py
git commit -m "feat: implement transform_dashboards() coordinate conversion and sheet zones"
```

---

## Task 4: transform_dashboards() — filter zone → slicer + visual interactions

Verify that filter zones resolve to the correct PBI table/field and produce the right slicer mode, and that visual interactions exclude the correct chart/slicer pairs.

**Files:**
- Modify: `tests/test_dashboard.py` (append)

- [ ] **Step 4.1: Append failing tests**

```python
def test_transform_filter_zone_becomes_slicer():
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "filter", "name": "Sheet1",
            "param_field": "Region",
            "param_datasource_id": "federated.abc",
            "mode": "dropdown",
            "x": 0, "y": 0, "w": 10000, "h": 10000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    v = pages[0]["visuals"][0]
    assert v["visual_type"] == "slicer"
    assert v["field_entity"] == "orders"
    assert v["field_property"] == "Region"
    assert v["slicer_mode"] == "Dropdown"
    assert v["scoped_to_sheet"] == "Sheet1"


def test_transform_slicer_mode_radiolist():
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "filter", "name": "Sheet1",
            "param_field": "Region",
            "param_datasource_id": "federated.abc",
            "mode": "radiolist",
            "x": 0, "y": 0, "w": 10000, "h": 10000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    assert pages[0]["visuals"][0]["slicer_mode"] == "Basic"


def test_transform_filter_unresolved_field_skipped():
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "filter", "name": "Sheet1",
            "param_field": "UnknownField",
            "param_datasource_id": "federated.abc",
            "mode": "dropdown",
            "x": 0, "y": 0, "w": 10000, "h": 10000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    assert pages[0]["visuals"] == []


def test_transform_visual_interactions_nofilter():
    """Slicer scoped to Sheet1 must NoFilter all charts that are NOT Sheet1."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [
            {
                "zone_type": "sheet", "name": "Sheet1",
                "x": 0, "y": 0, "w": 50000, "h": 100000,
            },
            {
                "zone_type": "sheet", "name": "Sheet2",
                "x": 50000, "y": 0, "w": 50000, "h": 100000,
            },
            {
                "zone_type": "filter", "name": "Sheet1",  # scoped to Sheet1 only
                "param_field": "Region",
                "param_datasource_id": "federated.abc",
                "mode": "dropdown",
                "x": 0, "y": 0, "w": 10000, "h": 10000,
            },
        ],
    }]
    workbook = {
        "datasources": [{
            "name": "federated.abc",
            "columns": [{"name": "Region", "source_table": "orders"}],
        }]
    }
    transformed = {
        "visuals": [
            {"name": "Sheet1", "page_name": "Sheet1", "mark_type": "Bar",
             "table": "orders", "row_fields": [], "col_fields": []},
            {"name": "Sheet2", "page_name": "Sheet2", "mark_type": "Bar",
             "table": "orders", "row_fields": [], "col_fields": []},
        ]
    }
    pages = transform_dashboards(dashboards, workbook, transformed)
    interactions = pages[0]["visual_interactions"]
    # slicer (dash_visual_3) should NoFilter Sheet2 chart (dash_visual_2) only
    assert len(interactions) == 1
    assert interactions[0]["source"] == "dash_visual_3"
    assert interactions[0]["target"] == "dash_visual_2"
    assert interactions[0]["type"] == "NoFilter"


def test_transform_no_interactions_when_slicer_matches_all_charts():
    """When all charts are scoped to the same sheet as the slicer → no interactions needed."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [
            {
                "zone_type": "sheet", "name": "Sheet1",
                "x": 0, "y": 0, "w": 100000, "h": 80000,
            },
            {
                "zone_type": "filter", "name": "Sheet1",
                "param_field": "Region",
                "param_datasource_id": "federated.abc",
                "mode": "dropdown",
                "x": 0, "y": 80000, "w": 20000, "h": 20000,
            },
        ],
    }]
    workbook = {
        "datasources": [{
            "name": "federated.abc",
            "columns": [{"name": "Region", "source_table": "orders"}],
        }]
    }
    transformed = {
        "visuals": [
            {"name": "Sheet1", "page_name": "Sheet1", "mark_type": "Bar",
             "table": "orders", "row_fields": [], "col_fields": []},
        ]
    }
    pages = transform_dashboards(dashboards, workbook, transformed)
    assert pages[0]["visual_interactions"] == []
```

- [ ] **Step 4.2: Run to verify failures**

```
uv run pytest tests/test_dashboard.py -v -k "test_transform_filter or test_transform_visual or test_transform_slicer or test_transform_no_inter"
```

Expected: All new tests FAIL

- [ ] **Step 4.3: Run tests again — `transform_dashboards` already handles this**

The implementation written in Task 3 already handles filter zones and visual interactions. Run:

```
uv run pytest tests/test_dashboard.py -v
```

Expected: All tests PASS (the Task 3 implementation covers filter zones and interactions).

If `test_transform_visual_interactions_nofilter` fails, check that `visual_idx` increments correctly for both sheet and filter zones in `transform_dashboards`.

- [ ] **Step 4.4: Full suite check**

```
uv run pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 4.5: Commit**

```
git add tests/test_dashboard.py
git commit -m "test: add filter zone, slicer mode, and visual interaction tests"
```

---

## Task 5: write_dashboard_pages() — page skeleton + pages.json update

Write page folders, `page.json` (with optional `visualInteractions`), and append new section IDs to the existing `pages.json`.

**Files:**
- Modify: `tests/test_dashboard.py` (append)
- Modify: `tab_to_pbi/dashboard.py` (replace `write_dashboard_pages` stub + add helpers)

- [ ] **Step 5.1: Append failing tests**

```python
import json
import tempfile
from tab_to_pbi.dashboard import write_dashboard_pages


def _make_empty_pages_json(pages_dir):
    """Seed a pages.json as the existing generate() would have written it."""
    pages_dir.mkdir(parents=True, exist_ok=True)
    content = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": ["ReportSection1"],
        "activePageName": "ReportSection1",
    }
    (pages_dir / "pages.json").write_text(json.dumps(content))


def test_write_creates_page_folder():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        report_dir = tmp / "Test.Report" / "definition"
        pages_dir = report_dir / "pages"
        _make_empty_pages_json(pages_dir)

        pages = [{
            "page_name": "Dashboard_Overview", "display_name": "Overview",
            "width": 1280, "height": 720,
            "visuals": [], "visual_interactions": [], "unsupported": [],
        }]
        write_dashboard_pages(pages, tmp, "Test")
        assert (pages_dir / "DashboardSection1").is_dir()


def test_write_page_json_content():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        report_dir = tmp / "Test.Report" / "definition"
        pages_dir = report_dir / "pages"
        _make_empty_pages_json(pages_dir)

        pages = [{
            "page_name": "Dashboard_Overview", "display_name": "Overview",
            "width": 1280, "height": 720,
            "visuals": [], "visual_interactions": [], "unsupported": [],
        }]
        write_dashboard_pages(pages, tmp, "Test")
        page_json = json.loads((pages_dir / "DashboardSection1" / "page.json").read_text())
        assert page_json["displayName"] == "Overview"
        assert page_json["width"] == 1280
        assert page_json["height"] == 720
        assert page_json["displayOption"] == "FitToPage"


def test_write_page_json_with_interactions():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pages_dir = tmp / "Test.Report" / "definition" / "pages"
        _make_empty_pages_json(pages_dir)

        pages = [{
            "page_name": "Dashboard_Overview", "display_name": "Overview",
            "width": 1280, "height": 720, "unsupported": [],
            "visuals": [],
            "visual_interactions": [
                {"source": "dash_visual_2", "target": "dash_visual_3", "type": "NoFilter"}
            ],
        }]
        write_dashboard_pages(pages, tmp, "Test")
        page_json = json.loads((pages_dir / "DashboardSection1" / "page.json").read_text())
        assert "visualInteractions" in page_json
        assert page_json["visualInteractions"][0]["type"] == "NoFilter"


def test_write_updates_pages_json():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pages_dir = tmp / "Test.Report" / "definition" / "pages"
        _make_empty_pages_json(pages_dir)

        pages = [
            {
                "page_name": "Dashboard_A", "display_name": "A",
                "width": 1280, "height": 720,
                "visuals": [], "visual_interactions": [], "unsupported": [],
            },
            {
                "page_name": "Dashboard_B", "display_name": "B",
                "width": 1280, "height": 720,
                "visuals": [], "visual_interactions": [], "unsupported": [],
            },
        ]
        write_dashboard_pages(pages, tmp, "Test")
        pages_json = json.loads((pages_dir / "pages.json").read_text())
        assert "DashboardSection1" in pages_json["pageOrder"]
        assert "DashboardSection2" in pages_json["pageOrder"]
        assert "ReportSection1" in pages_json["pageOrder"]   # existing sheet page preserved
        assert pages_json["activePageName"] == "ReportSection1"  # unchanged


def test_write_returns_report_entries():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pages_dir = tmp / "Test.Report" / "definition" / "pages"
        _make_empty_pages_json(pages_dir)

        pages = [{
            "page_name": "Dashboard_Overview", "display_name": "Overview",
            "width": 1280, "height": 720, "unsupported": [],
            "visuals": [
                {"visual_type": "chart", "source_sheet": "Sale Map",
                 "visual_id": "dash_visual_1", "x": 0, "y": 0, "width": 100, "height": 100,
                 "mark_type": "Bar", "table": "orders", "row_fields": [], "col_fields": []},
                {"visual_type": "slicer", "field_property": "Region",
                 "visual_id": "dash_visual_2", "x": 0, "y": 0, "width": 50, "height": 30,
                 "field_entity": "orders", "slicer_mode": "Dropdown", "scoped_to_sheet": "Sale Map"},
            ],
            "visual_interactions": [],
        }]
        result = write_dashboard_pages(pages, tmp, "Test")
        assert result[0]["name"] == "Overview"
        assert result[0]["status"] == "migrated"
        assert "Sale Map" in result[0]["sheets_placed"]
        assert "Region" in result[0]["slicers_placed"]
```

- [ ] **Step 5.2: Run to verify failures**

```
uv run pytest tests/test_dashboard.py -v -k "test_write"
```

Expected: All new tests FAIL — `write_dashboard_pages` returns `[]`

- [ ] **Step 5.3: Replace `write_dashboard_pages` stub and add page-writing helpers in `dashboard.py`**

Replace the stub `write_dashboard_pages` function with:

```python
def write_dashboard_pages(
    dashboard_pages: list[dict],
    output_dir: Path,
    stem: str,
) -> list[dict]:
    """Write dashboard pages to PBIR output. Returns migration report entries."""
    if not dashboard_pages:
        return []

    report_dir = output_dir / f"{stem}.Report"
    pages_dir = report_dir / "definition" / "pages"
    report_entries = []
    new_section_ids = []

    for i, page in enumerate(dashboard_pages):
        section_id = f"DashboardSection{i + 1}"
        new_section_ids.append(section_id)
        page_dir = pages_dir / section_id
        page_dir.mkdir(exist_ok=True)

        _write_dashboard_page_json(page_dir, page)

        for visual in page["visuals"]:
            visual_dir = page_dir / "visuals" / visual["visual_id"]
            visual_dir.mkdir(parents=True, exist_ok=True)
            _write_dashboard_visual_json(visual_dir, visual)

        sheets_placed = [v["source_sheet"] for v in page["visuals"] if v["visual_type"] == "chart"]
        slicers_placed = [v["field_property"] for v in page["visuals"] if v["visual_type"] == "slicer"]
        report_entries.append({
            "name": page["display_name"],
            "status": "migrated" if not page.get("unsupported") else "partial",
            "sheets_placed": sheets_placed,
            "slicers_placed": slicers_placed,
            "unsupported": page.get("unsupported", []),
        })

    _update_pages_manifest(pages_dir, new_section_ids)
    return report_entries


def _write_dashboard_page_json(page_dir: Path, page: dict) -> None:
    content: dict = {
        "$schema": f"{_SCHEMA_BASE}/definition/page/2.1.0/schema.json",
        "name": page_dir.name,
        "displayName": page["display_name"],
        "displayOption": "FitToPage",
        "height": page["height"],
        "width": page["width"],
    }
    if page.get("visual_interactions"):
        content["visualInteractions"] = page["visual_interactions"]
    (page_dir / "page.json").write_text(json.dumps(content, indent=2))


def _write_dashboard_visual_json(visual_dir: Path, visual: dict) -> None:
    if visual["visual_type"] == "chart":
        content = _build_chart_visual(visual_dir.name, visual)
    elif visual["visual_type"] == "slicer":
        content = _build_slicer_visual(visual_dir.name, visual)
    else:
        content = _build_textbox_visual(visual_dir.name, visual)
    (visual_dir / "visual.json").write_text(json.dumps(content, indent=2))


def _update_pages_manifest(pages_dir: Path, new_section_ids: list[str]) -> None:
    pages_json = pages_dir / "pages.json"
    content = json.loads(pages_json.read_text())
    content["pageOrder"].extend(new_section_ids)
    pages_json.write_text(json.dumps(content, indent=2))


def _base_container(name: str, visual: dict) -> dict:
    return {
        "$schema": f"{_SCHEMA_BASE}/definition/visualContainer/1.0.0/schema.json",
        "name": name,
        "position": {
            "x": visual["x"],
            "y": visual["y"],
            "z": 0,
            "width": visual["width"],
            "height": visual["height"],
        },
    }


def _build_chart_visual(name: str, visual: dict) -> dict:
    visual_type = MARK_TO_VISUAL.get(visual["mark_type"], "tableEx")
    table = visual["table"]
    row_fields = visual.get("row_fields", [])
    col_fields = visual.get("col_fields", [])

    if visual_type in _VISUAL_ROLES:
        cat_role, val_role, cat_shelf, val_shelf = _VISUAL_ROLES[visual_type]
        cat_fields = row_fields if cat_shelf == "row" else col_fields
        val_fields = col_fields if val_shelf == "col" else row_fields
        query_state = {
            cat_role: {"projections": [_make_projection(table, f) for f in cat_fields]},
            val_role: {"projections": [_make_projection(table, f) for f in val_fields]},
        }
    else:
        all_fields = row_fields + [f for f in col_fields if f not in row_fields]
        query_state = {
            "Values": {"projections": [_make_projection(table, f) for f in all_fields]}
        }

    container = _base_container(name, visual)
    container["visual"] = {"visualType": visual_type, "query": {"queryState": query_state}}
    return container


def _build_slicer_visual(name: str, visual: dict) -> dict:
    projection = {
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": visual["field_entity"]}},
                "Property": visual["field_property"],
            }
        },
        "queryRef": f"{visual['field_entity']}.{visual['field_property']}",
        "active": True,
    }
    container = _base_container(name, visual)
    container["visual"] = {
        "visualType": "slicer",
        "query": {"queryState": {"Values": {"projections": [projection]}}},
        "objects": {
            "data": [{"properties": {
                "mode": {"expr": {"Literal": {"Value": f"'{visual['slicer_mode']}'"}}},
            }}]
        },
        "drillFilterOtherVisuals": True,
    }
    return container


def _build_textbox_visual(name: str, visual: dict) -> dict:
    container = _base_container(name, visual)
    container["visual"] = {
        "visualType": "textbox",
        "objects": {
            "general": [{"properties": {
                "paragraphs": [{"textRuns": [{"value": visual["text"]}]}]
            }}]
        },
    }
    return container
```

- [ ] **Step 5.4: Run tests**

```
uv run pytest tests/test_dashboard.py -v
```

Expected: All tests PASS

- [ ] **Step 5.5: Full suite check**

```
uv run pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 5.6: Commit**

```
git add tab_to_pbi/dashboard.py tests/test_dashboard.py
git commit -m "feat: implement write_dashboard_pages() with page.json and pages.json update"
```

---

## Task 6: write_dashboard_pages() — visual.json output tests

Verify the visual.json files written for chart, slicer, and textbox visuals have the correct PBIR structure.

**Files:**
- Modify: `tests/test_dashboard.py` (append)

- [ ] **Step 6.1: Append failing tests**

```python
def _write_single_visual(visual_dict):
    """Helper: run write_dashboard_pages with one visual, return its visual.json content."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pages_dir = tmp / "Test.Report" / "definition" / "pages"
        _make_empty_pages_json(pages_dir)
        pages = [{
            "page_name": "Dashboard_Test", "display_name": "Test",
            "width": 1280, "height": 720,
            "visuals": [visual_dict],
            "visual_interactions": [], "unsupported": [],
        }]
        write_dashboard_pages(pages, tmp, "Test")
        visual_path = pages_dir / "DashboardSection1" / "visuals" / visual_dict["visual_id"] / "visual.json"
        return json.loads(visual_path.read_text())


def test_chart_visual_json_structure():
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "chart",
        "x": 10, "y": 20, "width": 500, "height": 300,
        "source_sheet": "Sheet1", "mark_type": "Bar", "table": "orders",
        "row_fields": [{"name": "Region", "is_measure": False, "table": "orders"}],
        "col_fields": [{"name": "Sum Sales", "is_measure": True, "table": "orders"}],
    }
    v = _write_single_visual(visual)
    assert v["name"] == "dash_visual_1"
    assert v["position"]["x"] == 10
    assert v["position"]["y"] == 20
    assert v["position"]["width"] == 500
    assert v["position"]["height"] == 300
    assert v["visual"]["visualType"] == "barChart"
    assert "Category" in v["visual"]["query"]["queryState"]
    assert "Y" in v["visual"]["query"]["queryState"]


def test_slicer_visual_json_structure():
    visual = {
        "visual_id": "dash_visual_2", "visual_type": "slicer",
        "x": 100, "y": 50, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Region",
        "slicer_mode": "Dropdown", "scoped_to_sheet": "Sheet1",
    }
    v = _write_single_visual(visual)
    assert v["visual"]["visualType"] == "slicer"
    assert v["position"]["x"] == 100
    proj = v["visual"]["query"]["queryState"]["Values"]["projections"][0]
    assert proj["field"]["Column"]["Expression"]["SourceRef"]["Entity"] == "orders"
    assert proj["field"]["Column"]["Property"] == "Region"
    mode_val = v["visual"]["objects"]["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"]
    assert mode_val == "'Dropdown'"
    assert v["visual"]["drillFilterOtherVisuals"] is True


def test_textbox_visual_json_structure():
    visual = {
        "visual_id": "dash_visual_3", "visual_type": "textbox",
        "x": 5, "y": 5, "width": 1270, "height": 30,
        "text": "Executive Overview",
    }
    v = _write_single_visual(visual)
    assert v["visual"]["visualType"] == "textbox"
    paras = v["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
    assert paras[0]["textRuns"][0]["value"] == "Executive Overview"


def test_slicer_between_mode():
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "slicer",
        "x": 0, "y": 0, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Order Date",
        "slicer_mode": "Between", "scoped_to_sheet": "ShippingTrend",
    }
    v = _write_single_visual(visual)
    mode_val = v["visual"]["objects"]["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"]
    assert mode_val == "'Between'"
```

- [ ] **Step 6.2: Run to verify failures**

```
uv run pytest tests/test_dashboard.py -v -k "test_chart_visual or test_slicer_visual or test_textbox or test_slicer_between"
```

Expected: FAIL — visual.json files are not written yet (stubs from Task 1 returned `[]`)

- [ ] **Step 6.3: Run all tests — Task 5 implementation already covers this**

The `_build_chart_visual`, `_build_slicer_visual`, `_build_textbox_visual` functions added in Task 5 should handle all visual writing. Run:

```
uv run pytest tests/test_dashboard.py -v
```

Expected: All tests PASS

- [ ] **Step 6.4: Full suite check**

```
uv run pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 6.5: Commit**

```
git add tests/test_dashboard.py
git commit -m "test: add visual.json content tests for chart, slicer, textbox"
```

---

## Task 7: Wire into main.py + migration report

Add the dashboard pipeline to `main.py`, run against Superstore.twb, verify the migration report has a `dashboards` key, and confirm all existing tests still pass.

**Files:**
- Modify: `tab_to_pbi/main.py`

- [ ] **Step 7.1: Add dashboard import and pipeline calls to `main.py`**

At the top of `main.py`, after the existing imports, add:

```python
from tab_to_pbi.dashboard import parse_dashboards_from_path, transform_dashboards, write_dashboard_pages
```

In `main()`, replace the existing migration report block:

```python
    report_file = output_dir / f"{input_path.stem}.migration_report.json"
    report_file.write_text(json.dumps(transformed.get("report", {}), indent=2))
```

with:

```python
    # Dashboard pages
    dashboards = parse_dashboards_from_path(input_path)
    dashboard_pages = transform_dashboards(dashboards, workbook, transformed)
    dashboard_report = write_dashboard_pages(dashboard_pages, output_dir, input_path.stem)

    # Migration report
    report_data = dict(transformed.get("report", {}))
    report_data["dashboards"] = dashboard_report
    report_file = output_dir / f"{input_path.stem}.migration_report.json"
    report_file.write_text(json.dumps(report_data, indent=2))
```

- [ ] **Step 7.2: Run full test suite to confirm no regressions**

```
uv run pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 7.3: Run end-to-end against Superstore.twb**

```
uv run tab_to_pbi/main.py input/Superstore.twb
```

Expected output includes lines like:
```
Output: output\Superstore.Report
Report: output\Superstore.migration_report.json
```
And the validator section at the end exits with 0 errors (the same result as before this change).

- [ ] **Step 7.4: Verify dashboard pages in pages.json**

```
python -c "import json; d=json.load(open('output/Superstore.Report/definition/pages/pages.json')); print(d['pageOrder'])"
```

Expected: List contains both `ReportSectionN` entries (existing sheet pages) AND `DashboardSection1` through `DashboardSection6`.

- [ ] **Step 7.5: Verify migration report has dashboards key**

```
python -c "import json; r=json.load(open('output/Superstore.migration_report.json')); print([d['name'] for d in r['dashboards']])"
```

Expected: `['Commission Model', 'Customers', 'Order Details', 'Overview', 'Product', 'Shipping']`

- [ ] **Step 7.6: Manual PBI Desktop verification — P2 checkpoint**

Open `output/Superstore.Report` in PBI Desktop. Check that the page list shows 6 dashboard pages alongside the existing sheet pages. No errors on open.

*Confirm back before proceeding to P3.*

- [ ] **Step 7.7: Full suite one more time**

```
uv run pytest tests/ -v
```

Expected: All tests PASS (count should be previous count + new dashboard tests)

- [ ] **Step 7.8: Commit**

```
git add tab_to_pbi/main.py tab_to_pbi/dashboard.py
git commit -m "feat: wire dashboard pipeline into main.py with migration report output"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task that covers it |
|---|---|
| parse_dashboards() — zone types (sheet, filter, text, title, skip others) | Task 1 |
| parse_dashboards() — coordinates from XML | Task 1, verified in Task 2 |
| paramctrl zones excluded | Task 2 |
| Coordinate scaling to 1280×720 | Task 3 |
| sheet zone → chart visual dict with mark_type/table/fields | Task 3 |
| filter zone → slicer dict with field_entity/field_property | Task 4 |
| slicer_mode mapping from Tableau modes | Task 4 |
| visual_interactions NoFilter for non-scoped pairs | Task 4 |
| write page.json with schema, displayName, width/height | Task 5 |
| write page.json visualInteractions field | Task 5 |
| pages.json appended (not overwritten), activePageName preserved | Task 5 |
| migration report entries returned | Task 5 |
| chart visual.json — correct visualType, projections, position | Task 6 |
| slicer visual.json — slicer structure, mode, drillFilterOtherVisuals | Task 6 |
| textbox visual.json — paragraphs/textRuns structure | Task 6 |
| Wire into main.py (3-line addition) | Task 7 |
| migration_report.json gains "dashboards" key | Task 7 |
| PBI Desktop verification (manual) | Task 7 step 7.6 |

**Placeholder scan:** None found.

**Type consistency check:**
- `parse_dashboards()` returns `list[dict]` — used as first arg to `transform_dashboards()` ✓
- `transform_dashboards()` returns `list[dict]` — used as first arg to `write_dashboard_pages()` ✓
- `write_dashboard_pages()` returns `list[dict]` — assigned to `dashboard_report`, stored in `report_data["dashboards"]` ✓
- `visual["visual_type"]` values (`"chart"`, `"slicer"`, `"textbox"`) used consistently in transform and write ✓
- `_scale(tab_val, pbi_dim)` takes ints, returns int — consistent with zone `x/y/w/h` int values ✓
