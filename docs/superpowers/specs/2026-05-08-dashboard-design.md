# Dashboard Migration Design — Tableau Dashboard → PBI Page

**Date:** 2026-05-08  
**Branch:** dashboard  
**Status:** Approved

---

## Overview

Add Tableau dashboard → PBI page migration to the existing pipeline. Each Tableau dashboard
becomes an additional PBI report page containing repositioned chart visuals and slicer visuals.
Existing sheet-per-page behaviour is unchanged.

---

## Goals

- One PBI page per Tableau dashboard, containing all the worksheets and filters from that dashboard
- Filter zones become PBI slicer visuals scoped to the same worksheets they filter in Tableau
- Layout preserved via coordinate scaling from Tableau 100000-unit space to PBI 1280×720
- Zero changes to existing parser.py, transformer.py, generator.py, translator.py
- Dashboard pages pass through the existing PBIR validator automatically

---

## Architecture

```
tab_to_pbi/
├── parser.py        ← unchanged
├── transformer.py   ← unchanged
├── generator.py     ← unchanged
├── translator.py    ← unchanged
├── dashboard.py     ← NEW
└── main.py          ← +3 lines at end of pipeline
```

### dashboard.py functions

| Function | Responsibility |
|---|---|
| `parse_dashboards(root)` | Walk `<dashboards>` XML → list of dashboard dicts (raw Tableau data) |
| `transform_dashboards(dashboards, workbook, transformed)` | Zone trees → PBI page dicts (resolved PBI entities, pixel positions, slicer modes, visual interactions) |
| `write_dashboard_pages(dashboard_pages, output_dir, stem)` | Write PBIR page folders, visual.json files, update pages.json |

`dashboard.py` imports helpers from existing modules without modifying them:
- `generator._write_visual()` — writes chart visual.json (already PBIR-compliant)
- Field/table lookup patterns from `transformer.py` column maps

### main.py addition (3 lines)

```python
from tab_to_pbi.dashboard import parse_dashboards, transform_dashboards, write_dashboard_pages

dashboards = parse_dashboards(root)
dashboard_pages = transform_dashboards(dashboards, workbook, transformed)
write_dashboard_pages(dashboard_pages, output_dir, stem)
```

Added after the existing pipeline (parse → transform → translate → generate → validate).
The `root` XML element is already available in main.py from the parse step.

---

## Data Model

### parse_dashboards() output — one dict per dashboard

```python
{
  "name": "Overview",
  "width": 1000,           # from <size minwidth='1000'>
  "height": 620,           # from <size minheight='620'>
  "title": "Executive Overview - Profitability",
  "zones": [
    {
      "zone_type": "sheet",
      "name": "Sale Map",               # matches a worksheet name
      "x": 570, "y": 17816,
      "w": 84458, "h": 48420           # Tableau 100000-unit space
    },
    {
      "zone_type": "filter",
      "name": "Sale Map",               # scoped-to worksheet
      "param_field": "Region",          # extracted from [ds].[none:Region:nk]
      "param_datasource_id": "federated.10nnk8d1vgmw8q17yu76u06pnbcj",
      "mode": "dropdown",
      "x": 85678, "y": 18966,
      "w": 13102, "h": 7471
    },
    {
      "zone_type": "text",
      "text": "Enter new quota...",
      "x": 410, "y": 4314,
      "w": 99180, "h": 2765
    }
    # paramctrl, color, empty → omitted
  ]
}
```

### transform_dashboards() output — one dict per PBI page

```python
{
  "page_name": "Dashboard_Overview",
  "display_name": "Overview",
  "width": 1280,
  "height": 720,
  "visuals": [
    {
      "visual_id": "dash_visual_1",
      "x": 7, "y": 127, "width": 1081, "height": 348,   # scaled pixels
      "visual_type": "filledMap",
      "source_sheet": "Sale Map",
      "query": { ... }          # copied from transformed["pages"]["Sale Map"]
    },
    {
      "visual_id": "dash_visual_2",
      "x": 1095, "y": 137, "width": 168, "height": 54,
      "visual_type": "slicer",
      "slicer_mode": "Dropdown",
      "field_entity": "orders",         # resolved PBI table name
      "field_property": "Region",
      "scoped_to_sheet": "Sale Map"
    }
  ],
  "visual_interactions": [
    {"source": "dash_visual_2", "target": "dash_visual_3", "type": "NoFilter"}
  ]
}
```

---

## Zone Tree Flattening

Tableau zone `x, y, w, h` are **absolute** (not relative to parent). Walk the tree
recursively and collect leaf content zones only.

### Zone classification

| `type-v2` value | Classification | Action |
|---|---|---|
| absent + has `name` | `sheet` | Extract |
| `filter` | `filter` | Extract → slicer |
| `text` | `text` | Extract → textbox |
| `title` | `title` | Extract → textbox |
| `layout-flow` | container | Recurse |
| `layout-basic` | container | Recurse |
| `paramctrl` | skip | Log unsupported |
| `color` | skip | Silent skip |
| `empty` | skip | Silent skip |

### Coordinate conversion (Tableau → PBI 1280×720)

```python
pbi_x = round((tab_x / 100000) * 1280)
pbi_y = round((tab_y / 100000) * 720)
pbi_w = round((tab_w / 100000) * 1280)
pbi_h = round((tab_h / 100000) * 720)
```

### Tableau filter mode → PBI slicer mode

| Tableau `mode` | PBI slicer `objects.data.mode` |
|---|---|
| `dropdown` | `'Dropdown'` |
| `slider` | `'Between'` |
| `compact` | `'Dropdown'` |
| `type_in` | `'Dropdown'` |
| absent | `'Basic'` |

---

## Visual Interactions (Filter Scoping)

Each filter zone has `name` = the worksheet it is scoped to. For every slicer, set
`NoFilter` on every chart visual it is NOT scoped to.

```python
for slicer in slicers:
    for chart in charts:
        if chart["source_sheet"] != slicer["scoped_to_sheet"]:
            visual_interactions.append({
                "source": slicer["visual_id"],
                "target": chart["visual_id"],
                "type": "NoFilter"
            })
```

Written to `page.json` alongside existing width/height fields:

```json
{
  "$schema": "...page/2.1.0/schema.json",
  "name": "Dashboard_Overview",
  "displayName": "Overview",
  "width": 1280,
  "height": 720,
  "displayOption": "FitToPage",
  "visualInteractions": [
    {"source": "dash_visual_2", "target": "dash_visual_4", "type": "NoFilter"}
  ]
}
```

---

## PBIR Output — Slicer Visual Structure

Conforms to `visualContainer/1.0.0/schema.json`. Based on official Microsoft schema examples.

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.0.0/schema.json",
  "name": "dash_visual_2",
  "position": { "x": 1095, "y": 137, "z": 0, "width": 168, "height": 54 },
  "visual": {
    "visualType": "slicer",
    "query": {
      "queryState": {
        "Values": {
          "projections": [{
            "field": {
              "Column": {
                "Expression": { "SourceRef": { "Entity": "orders" } },
                "Property": "Region"
              }
            },
            "queryRef": "orders.Region",
            "active": true
          }]
        }
      }
    },
    "objects": {
      "data": [{"properties": {"mode": {"expr": {"Literal": {"Value": "'Dropdown'"}}}}}]
    },
    "drillFilterOtherVisuals": true
  }
}
```

---

## PBIR Output — Textbox Visual Structure

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.0.0/schema.json",
  "name": "dash_visual_3",
  "position": { "x": 5, "y": 22, "z": 0, "width": 1270, "height": 25 },
  "visual": {
    "visualType": "textbox",
    "objects": {
      "general": [{"properties": {"paragraphs": [{"textRuns": [{"value": "Executive Overview"}]}]}}]
    }
  }
}
```

---

## Migration Report Addition

`migration_report.json` gains a `"dashboards"` key:

```json
"dashboards": [
  {
    "name": "Overview",
    "status": "migrated",
    "sheets_placed": ["Sale Map", "Sales by Segment", "Sales by Product"],
    "slicers_placed": ["Region", "Order Date", "Profit Ratio"],
    "unsupported": []
  },
  {
    "name": "Commission Model",
    "status": "partial",
    "sheets_placed": ["QuotaAttainment", "CommissionProjection"],
    "slicers_placed": [],
    "unsupported": [
      "paramctrl: New Quota (type_in)",
      "paramctrl: Base Salary (type_in)",
      "paramctrl: Commission Rate (slider)"
    ]
  }
]
```

---

## Incremental Build & Test Phases

| Phase | What gets built | Automated | Manual (PBI Desktop) |
|---|---|---|---|
| P1 — Parse | `parse_dashboards()` | `pytest tests/test_dashboard.py` | — |
| P2 — Page skeleton | Page folders, page.json, pages.json update | unit tests | Dashboard page names appear in page list |
| P3 — Worksheet visuals | Chart visuals at scaled positions | unit tests | Chart visuals appear at correct layout |
| P4 — Slicer visuals | Slicer visual.json + visualInteractions | unit tests | Slicers filter only scoped charts |
| P5 — Text/title zones | Textbox visuals | unit tests | Text labels and title visible |

**Test workbook progression:**
1. `Shipping` dashboard — 2 sheets, 0 filters → validates P1–P3
2. `Overview` dashboard — 3 sheets, 3 filters → validates P4
3. `Commission Model` dashboard — has paramctrl → validates unsupported logging
4. All 6 Superstore dashboards — full regression after P5

**Test file:** `tests/test_dashboard.py`

---

## Constraints

- No changes to parser.py, transformer.py, generator.py, translator.py
- All generated PBIR files pass the existing validator (already integrated in main.py)
- PBI Desktop verification is manual — user confirms each phase before proceeding
- Parameter controls (`paramctrl`) → logged as unsupported, no visual generated
- Color legend zones → silently skipped (PBI chart legends are automatic)
- Existing sheet pages (one per Tableau worksheet) are unaffected
