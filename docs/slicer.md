# Tableau Interactive Filter → PBI Slicer: Analysis & Architecture

## Background

This document captures the root cause analysis and architectural design for converting
Tableau's interactive filter cards (dropdowns, slicers) into PBI Slicer visuals in the
PBIR output. It is a reference for future implementation.

---

## Problem Statement

When migrating `simple_join_sorted_dropdown_crosstab.twb` (and any workbook with interactive
filter dropdowns), the Region filter card visible in Tableau's Sheet 1 is silently absent from
the converted PBI report. No slicer visual is generated.

---

## Root Cause

Tableau represents an interactive filter dropdown using **three separate XML locations** — none
of which is `<worksheet>/<table>/<view>/<filter>` (the only XPath the pipeline reads):

### 1. `<shared-views>/<filter>` — the filter definition

```xml
<shared-views>
  <shared-view name='federated.17kv7r10vp81pc1g60xgp0re1it8'>
    <filter class='categorical' column='[ds].[none:region:nk]'>
      <groupfilter function='level-members' level='[none:region:nk]'
                   user:ui-enumeration='all' user:ui-marker='enumerate' />
    </filter>
  </shared-view>
</shared-views>
```

`function='level-members'` + `user:ui-enumeration='all'` = "show all values, user-selectable
at runtime" (interactive slicer). No `<groupfilter function='member'>` children = no static
values.

### 2. `<worksheet>/<table>/<view>/<slices>` — sheet-level binding

```xml
<slices>
  <column>[federated...].[none:region:nk]</column>
</slices>
```

Declares which fields participate as interactive slicers on this sheet.

### 3. `<windows>/<window>/<cards>/<card type='filter'>` — UI card definition

```xml
<window class='worksheet' name='Sheet 1'>
  <cards>
    <edge name='right'>
      <strip size='300'>
        <card mode='dropdown' param='[federated...].[none:region:nk]' type='filter' />
      </strip>
    </edge>
  </cards>
</window>
```

`type='filter'` = this is an interactive filter card. `mode='dropdown'` = UI widget style.
`param` = the field. **This is the authoritative source** for which slicer appears on which
sheet.

### Pipeline failure chain

| Stage | What happens | Effect |
|---|---|---|
| `_parse_filters(sheet)` | Searches `./table/view/filter`; Sheet 1 has none | `sheet["filters"] = []` |
| `_parse_datasource_filters` | Finds shared-view filter; `_parse_filter_element` returns `{field: region, class: categorical}` — no `values` | `datasource_filters` has entry but no values |
| `_build_filter_entry` | `values = []` → `return None` (explicit skip) | Region filter dropped from `filterConfig` |
| Slicer visual | No code path reads `<slices>` or `<windows>/<card>` | No slicer visual generated |

---

## Tableau Filter Taxonomy

### Static Categorical Filter (data restriction)

**XML:** `<filter class='categorical'>` inside `./table/view/filter`

```xml
<filter class='categorical' column='[ds].[none:category:nk]'>
  <groupfilter function='union' user:ui-enumeration='inclusive'>
    <groupfilter function='member' level='[none:Category:nk]' member='"Furniture"' />
    <groupfilter function='member' level='[none:Category:nk]' member='"Technology"' />
  </groupfilter>
</filter>
```

**Key signals:** `function='union'` outer + `function='member'` inner children with explicit
values. `user:ui-enumeration='inclusive'`. Hard data restriction.

**Currently handled:** Yes — `_parse_filter_element` extracts `member` values.

### Interactive Slicer / Dropdown Filter

**XML:** Either inside `./table/view/filter` (per-sheet) or inside `<shared-views>` (cross-sheet)

```xml
<filter class='categorical' column='[ds].[none:region:nk]'>
  <groupfilter function='level-members' level='[none:region:nk]'
               user:ui-enumeration='all' user:ui-marker='enumerate' />
</filter>
```

**Key signals:** `function='level-members'` (single element, no children). `user:ui-enumeration='all'`.
No `member` children. Does NOT restrict data — exposes field for runtime user selection.

**Currently handled:** Partially parsed but discarded (`return None` in `_build_filter_entry`
because `values = []`). No slicer visual generated.

### Quantitative / Range Filter

**XML:** `<filter class='quantitative'>` inside `./table/view/filter`

```xml
<filter class='quantitative' column='[ds].[max:profit:qk]' included-values='in-range'>
  <min>1013.13</min>
  <max>6719.98</max>
</filter>
```

**Currently handled:** Yes — `_parse_filter_element` extracts `min`/`max`.

### Distinguishing Static vs. Interactive (deterministic rule)

| Attribute | Static | Interactive Slicer |
|---|---|---|
| `groupfilter function=` | `'union'` + `'member'` children | `'level-members'` only |
| `user:ui-enumeration=` | `'inclusive'` | `'all'` |
| `member` child elements | Yes (one per value) | None |
| In `<slices>` | May or may not appear | Always listed |
| `<card type='filter'>` in `<windows>` | Absent | Always present |

---

## PBI Slicer Visual Schema

The PBI slicer visual follows the official MS PBIR visual container schema
(`visualContainer/1.0.0/schema.json`). A complete slicer `visual.json`:

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.0.0/schema.json",
  "name": "visual_3",
  "position": { "x": 920, "y": 20, "z": 0, "width": 340, "height": 60, "tabOrder": 0 },
  "visual": {
    "visualType": "slicer",
    "query": {
      "queryState": {
        "Values": {
          "projections": [{
            "field": {
              "Column": {
                "Expression": { "SourceRef": { "Entity": "orders" } },
                "Property": "region"
              }
            },
            "queryRef": "orders.region",
            "active": true
          }]
        }
      }
    },
    "objects": {
      "data": [{ "properties": {
        "mode": { "expr": { "Literal": { "Value": "'Dropdown'" } } }
      }}],
      "selection": [{ "properties": {
        "singleSelect": { "expr": { "Literal": { "Value": "false" } } },
        "strictSingleSelect": { "expr": { "Literal": { "Value": "false" } } },
        "selectAllCheckboxEnabled": { "expr": { "Literal": { "Value": "true" } } }
      }}]
    },
    "drillFilterOtherVisuals": true
  }
}
```

**Key facts:**
- `visualType: "slicer"` (lowercase string)
- `queryState` role is always `"Values"` (single Column projection — never a Measure)
- `drillFilterOtherVisuals: true` — required for the slicer to cross-filter other visuals
- `objects.data[0].properties.mode` controls widget style: `'Dropdown'`, `'Basic'`, `'Between'`
- `objects.selection` — only written when `multi_select=True AND slicer_mode != "Between"`
- `objects.selection` is NEVER written for `Between` (range slider)

### Slicer Mode Mapping (from `dashboard.py:_SLICER_MODE_MAP`)

| Tableau `<card mode=>` | PBI `slicer_mode` | `multi_select` |
|---|---|---|
| `dropdown` | `Dropdown` | False |
| `radiolist` | `Basic` | False |
| `checkdropdown` | `Dropdown` | True |
| `slider` | `Between` | True |
| `compact` | `Dropdown` | False |
| `type_in` | `Dropdown` | False |
| `` (absent) | `Basic` | True |

---

## Existing Slicer Implementation

`dashboard.py:_build_slicer_visual()` (line 430) is a **complete, tested, working** slicer
visual generator already in the codebase. It is currently used only for Tableau dashboard
`type-v2="filter"` zones. The same logic needs to be available for worksheet filter cards.

**Input visual dict keys required by `_build_slicer_visual`:**

```python
{
    "field_entity": "orders",      # PBI table name
    "field_property": "region",    # physical column name
    "slicer_mode": "Dropdown",     # one of Dropdown / Basic / Between
    "multi_select": True,
    # _base_container keys:
    "x": 920, "y": 20, "width": 340, "height": 60,
}
```

**Circular import constraint:** `dashboard.py` imports from `generator.py`. Therefore
`generator.py` CANNOT import from `dashboard.py` — this would create a circular import
(`generator → dashboard → generator`). The slicer visual JSON construction must be inlined
in generator.py (it is ~20 lines of pure JSON assembly, no shared logic is lost).

`transformer.py` CAN safely import from `dashboard.py` because the dependency chain
`transformer → dashboard → generator` is a DAG with no cycle.

---

## Proposed Architecture (Synthesis)

### Design Decisions

- **`<windows>` is authoritative**: only generate a slicer on pages where Tableau explicitly
  shows a `<card type='filter'>`. Respects the original report author's intent.
- **Right side placement**: slicers go at `x=920`, stacked vertically at `y=20+60*i`, `width=340`,
  `height=60` each. Matches Tableau's right-panel layout.
- **Chart width adjustment**: when slicers are present on a page, chart visuals shrink to
  `width=900` (from default 560) to avoid overlapping the slicer column.
- **Mode mapping**: reuse `_SLICER_MODE_MAP` and `_SINGLE_SELECT_MODES` from `dashboard.py`.
- **Slicer visuals are first-class in the `visuals` list**: threaded through the same pipeline
  as chart visuals, distinguished by `mark_type == "Slicer"`.

### Data Flow

```
<windows>/<window class='worksheet' name='Sheet 1'>
    <cards>/<card type='filter' param='[ds].[none:region:nk]' mode='dropdown'>

parser._parse_window_filter_cards(root)
    → {"Sheet 1": [{"field": "region", "mode": "dropdown"}]}
    → stored as workbook["window_filter_cards"]

transformer._process_sheets (inside sheet loop for "Sheet 1"):
    card = {"field": "region", "mode": "dropdown"}
    entity = fmap.get("region") = "orders"
    slicer_mode = _SLICER_MODE_MAP["dropdown"] = "Dropdown"
    multi_select = "dropdown" not in _SINGLE_SELECT_MODES = False
    → appends slicer dict to visuals[]:
      { mark_type:"Slicer", page_name:"Sheet 1", field_entity:"orders",
        field_property:"region", slicer_mode:"Dropdown", multi_select:False,
        x:920, y:20, width:340, height:60 }

generator._write_page (for page "Sheet 1"):
    has_slicers = True → chart_width = 900
    chart visual: _write_visual(..., width=900)
    slicer visual: _write_slicer_visual(visual_dir, slicer_dict)
                   → writes visual.json with visualType:"slicer"
```

### File-by-File Changes

#### `parser.py` (~17 lines)

New function after `_parse_datasource_filters`:

```python
def _parse_window_filter_cards(root: ET.Element) -> dict[str, list[dict]]:
    """Return {sheet_name: [{"field": str, "mode": str}]} from <windows> filter cards.

    <windows> is the authoritative source: only sheets with a <card type='filter'>
    entry will have slicer visuals generated.
    """
    result: dict[str, list[dict]] = {}
    for window in root.findall("./windows/window[@class='worksheet']"):
        name = window.get("name", "")
        if not name:
            continue
        cards = []
        for card in window.findall("./cards/card[@type='filter']"):
            param = card.get("param", "")
            field = _extract_field_name(param) if param else ""
            if field and not field.startswith(":"):
                cards.append({"field": field, "mode": card.get("mode", "")})
        if cards:
            result[name] = cards
    return result
```

Add to `parse()` return dict:
```python
"window_filter_cards": _parse_window_filter_cards(root),
```

Optionally mark `is_slicer=True` in `_parse_filter_element` for `level-members` categorical
filters (documentation, no behavioral change):
```python
if cls == "categorical":
    members = [...]
    if members:
        entry["values"] = members
    else:
        entry["is_slicer"] = True  # level-members: no static values, interactive slicer
```

#### `transformer.py` (~25 lines)

Add imports at top:
```python
from tab_to_pbi.dashboard import _SLICER_MODE_MAP, _SINGLE_SELECT_MODES
```

Add `"Slicer"` to `_SUPPORTED_MARK_TYPES` to suppress false unsupported-type warnings.

Inside `_process_sheets` loop, after appending chart visual(s) for a sheet:
```python
cards = workbook.get("window_filter_cards", {}).get(sheet["name"], [])
for i, card in enumerate(cards):
    field = card["field"]
    physical = pmap.get(field, field)
    entity = fmap.get(field, fmap.get(physical, default_table))
    if not entity:
        unsupported_warnings.append(
            f"Sheet '{sheet['name']}': slicer field '{field}' not found in field map — skipped"
        )
        continue
    mode_raw = card["mode"]
    visuals.append({
        "mark_type": "Slicer",
        "page_name": sheet["name"],
        "name": f"slicer_{sheet['name']}_{physical}",
        "field_entity": entity,
        "field_property": physical,
        "slicer_mode": _SLICER_MODE_MAP.get(mode_raw, "Basic"),
        "multi_select": mode_raw not in _SINGLE_SELECT_MODES,
        "x": 920,
        "y": 20 + 60 * i,
        "width": 340,
        "height": 60,
    })
```

#### `generator.py` (~35 lines)

New `_write_slicer_visual` function (inlined — no import from dashboard.py to avoid circular
import):

```python
def _write_slicer_visual(visual_dir: Path, visual: dict) -> None:
    """Write visual.json for a slicer visual."""
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
    objects: dict = {
        "data": [{"properties": {
            "mode": {"expr": {"Literal": {"Value": f"'{visual['slicer_mode']}'"}}},
        }}],
    }
    if visual["slicer_mode"] != "Between" and visual.get("multi_select", False):
        objects["selection"] = [{"properties": {
            "singleSelect": {"expr": {"Literal": {"Value": "false"}}},
            "strictSingleSelect": {"expr": {"Literal": {"Value": "false"}}},
            "selectAllCheckboxEnabled": {"expr": {"Literal": {"Value": "true"}}},
        }}]
    container = {
        "$schema": f"{_SCHEMA_BASE}/definition/visualContainer/1.0.0/schema.json",
        "name": visual_dir.name,
        "position": {
            "x": visual["x"], "y": visual["y"], "z": 0,
            "width": visual["width"], "height": visual["height"], "tabOrder": 0,
        },
        "visual": {
            "visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [projection]}}},
            "objects": objects,
            "drillFilterOtherVisuals": True,
        },
    }
    (visual_dir / "visual.json").write_text(json.dumps(container, indent=2))
```

Modify `_write_visual` to accept `width: int = 560` parameter (replace hardcoded 560 in
position dict).

Modify `_write_page`:
```python
def _write_page(page_dir: Path, page_visuals: list[dict], base_visual_idx: int) -> None:
    has_slicers = any(v.get("mark_type") == "Slicer" for v in page_visuals)
    chart_width = 900 if has_slicers else 560
    ...
    for j, visual_info in enumerate(page_visuals):
        if visual_info.get("mark_type") == "Slicer":
            visual_dir = ...
            _write_slicer_visual(visual_dir, visual_info)
        elif visual_info.get("row_fields") or visual_info.get("col_fields"):
            ...
            _write_visual(visual_dir, visual_info, x_offset=20 + slot*620, width=chart_width)
            slot += 1
```

### Summary of Changes

| File | New/Changed | Approx Lines |
|---|---|---|
| `parser.py` | `_parse_window_filter_cards()` + `parse()` return key + optional `is_slicer` flag | +17 |
| `transformer.py` | 2 imports + slicer dict generation block in `_process_sheets` + `_SUPPORTED_MARK_TYPES` | +25 |
| `generator.py` | `_write_slicer_visual()` inlined + `_write_page` slicer dispatch + `_write_visual` width param | +35 |
| **Total** | 3 files, 0 new modules | **~77 lines** |

---

## Testing Plan

New unit tests to add:

1. **`test_parse_window_filter_cards`** — parse a minimal XML fragment with `<windows>/<card
   type='filter'>` and assert `{sheet_name: [{field, mode}]}` output.

2. **`test_slicer_not_generated_without_window_card`** — sheet has `<filter
   function='level-members'>` but no `<card type='filter'>` in `<windows>` → no slicer visual
   in output.

3. **`test_slicer_generated_for_window_card`** — sheet has both → slicer dict in `transformed["visuals"]`
   with correct `mark_type`, `field_entity`, `field_property`, `slicer_mode`, `position`.

4. **`test_slicer_mode_mapping`** — parametrize over `dropdown`, `radiolist`, `slider`, `` (empty),
   assert correct `slicer_mode` and `multi_select`.

5. **`test_slicer_visual_json`** — generator writes `visual.json` with `visualType:"slicer"`,
   correct `position`, `queryState.Values` projection.

6. **`test_chart_width_shrinks_with_slicers`** — page with slicer → chart visual gets `width=900`
   not `width=560`.

7. **`test_multiple_slicers_stacked`** — two filter cards on one sheet → two slicer visuals
   at `y=20` and `y=80`.

8. **E2E test** — run pipeline on `input/simple_join_sorted_dropdown_crosstab.twb` → assert
   Sheet 1 page contains a slicer visual.json with `region` field.

---

## Files Researched

- `tab_to_pbi/parser.py` — `_parse_filter_element` (843), `_parse_filters` (877), `_parse_datasource_filters` (931)
- `tab_to_pbi/transformer.py` — `_process_sheets` (394), `transform()` (103)
- `tab_to_pbi/generator.py` — `_write_visual` (1123), `_write_page` (943), `_build_filter_entry` (216), `_build_filter_config` (312)
- `tab_to_pbi/dashboard.py` — `_build_slicer_visual` (430), `_SLICER_MODE_MAP` (21), `_SINGLE_SELECT_MODES` (31), `_extract_filter_zone` (111)
- `input/simple_join_sorted_dropdown_crosstab.twb` — primary workbook showing all three filter signals
- `tests/test_dashboard.py` — existing slicer tests (40+ covering all modes and edge cases)
