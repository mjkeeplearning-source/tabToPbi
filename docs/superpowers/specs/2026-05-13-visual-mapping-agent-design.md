# Visual Mapping Agent — Design Spec

**Date:** 2026-05-13  
**Status:** Approved (revised after code review)  
**Goal:** Eliminate manual maintenance of `visual_conversion.md` and surface visual property gaps without destabilising the existing migration pipeline.

---

## Problem

Visual property mapping (Tableau → PBI) is currently:

1. **Manually maintained** — `visual_conversion.md` was started mid-project and is incomplete. Validated mappings discovered during bug fixes (e.g. CrossTab `valuesOnRow`) are sometimes not recorded.
2. **Hardcoded in the pipeline** — `MARK_TO_VISUAL` and `_VISUAL_ROLES` in `generator.py`/`transformer.py` are static dicts; adding a new mapping requires a code change.
3. **Discovered by trial and error** — undocumented PBI native visual properties (like `pivotTable.valuesOnRow`) are only found by manually fixing a report in PBI Desktop and inspecting the JSON.
4. **No confidence signal** — the pipeline cannot distinguish "validated in PBI Desktop" from "generated but never checked."

---

## Why PBI Schemas Don't Fully Cover Visual Properties

The MS PBIR schema (`microsoft/json-schemas/fabric/item/report`) defines:
- Container structure (`visualContainer/2.7.0`)
- Generic `objects` shape (`visualConfiguration/2.3.0`)
- Formatting object structure (`formattingObjectDefinitions/1.5.0`)

It does **not** enumerate visual-type-specific properties (`valuesOnRow` for `pivotTable`, axis config for `barChart`, etc.). The `objects` property is a free-form bag even in the latest schema version. Native built-in visual properties are only discoverable from PBI Desktop save output.

The PBI custom visuals API (`learn.microsoft.com/en-us/power-bi/developer/visuals/capabilities`) covers custom visual development only — not built-in native visuals.

**Ground truth for native PBI visual properties = PBI Desktop save output (`visual.json` files).**

---

## Architecture: Three Layers, Registry Covers Only Two

The existing pipeline has two layers that must not be conflated:

| Layer | Responsibility | Location |
|-------|---------------|----------|
| Semantic normalization | Tableau XML → normalised sheet dict (`mark_type`, `row_fields`, orientation flip, `_infer_mark_type()` for Automatic) | `transformer.py` — stays in code |
| PBIR role/projection templates | shelf → correct PBI `queryState` role per visual type | `generator.py` + registry layer 2 |
| PBIR object fragments | pre-built `objects` JSON snippets triggered by Tableau properties | `generator.py` + registry layer 3 |

**The registry covers only layers 2 and 3.** Semantic normalization (`_infer_mark_type`, Bar→Column orientation flip, pivot projection logic) stays in `transformer.py` as code. Moving it to data would create fragile branching for logic that has no reason to change.

---

## Solution: Approach C — Offline Registry Builder + Advisory Runtime

```
OFFLINE (run once, or after new validations)
──────────────────────────────────────────────────────────────────────
samples/validation_manifest.yaml         (user declares PBI-validated sheets)
  + output/<stem>.transformed.json        (Tableau source properties per sheet)
  + output/<stem>.Report/.../visual.json  (PBI output per sheet, with provenance)
  + samples/baselines/<type>_minimal.json (curated per-visual minimal baseline)
  + .pbir_schema_cache/ schemas           (structural validation)
  ↓
tab_to_pbi/visual_agent.py
  ↓
samples/visual_mappings.json             (machine-readable tiered registry)
docs/visual_conversion.md               (auto-generated, always accurate)

RUNTIME (each migration run)
──────────────────────────────────────────────────────────────────────
transformer.py / generator.py
  → reads visual_mappings.json for mark type lookup + object fragments
  → falls back to hardcoded constants if registry absent (fresh clone)
  → for unknown properties: Claude → output/<stem>.visual_mapping_suggestions.json
  → migration_report.json references suggestions, never promotes them

PROMOTION (after human review)
──────────────────────────────────────────────────────────────────────
User reviews output/<stem>.visual_mapping_suggestions.json
  → adds verified sheets to samples/validation_manifest.yaml
  → reruns visual_agent.py → registry updated
```

**`visual_agent.py` is the sole writer of `samples/visual_mappings.json`.** No pipeline migration run ever mutates the canonical registry.

---

## New Files

| File | Type | Purpose |
|------|------|---------|
| `samples/validation_manifest.yaml` | User-maintained | Declares which sheets/dashboards have been PBI Desktop verified |
| `samples/visual_mappings.json` | Generated (agent only) | Machine-readable tiered registry |
| `samples/baselines/<type>_minimal.json` | Curated | Per-visual minimal baseline for object diffing |
| `tab_to_pbi/visual_agent.py` | New module | Offline registry builder — sole registry writer |
| `tab_to_pbi/visual_mapper.py` | New module | Thin runtime registry reader (lookup only, no assembly) |

## Modified Files

| File | Change |
|------|--------|
| `tab_to_pbi/generator.py` | Add `_provenance` fields to generated `visual.json`; consult registry for object fragments (P2) |
| `tab_to_pbi/transformer.py` | Consult registry for mark-type lookup (P2); semantic normalization stays in code |
| `tab_to_pbi/main.py` | Load registry at startup (P2); add `visual_mapping_suggestions` section to migration report (P3) |
| `docs/visual_conversion.md` | No longer hand-edited; regenerated by `visual_agent.py` |

---

## Confidence Model

Two separate fields — provenance and LLM score are not mixed:

| Field | Type | Meaning |
|-------|------|---------|
| `status` | `"validated" \| "generated" \| "inferred"` | Provenance/review state, set by `visual_agent.py` |
| `score` | `float 0.0–1.0` (optional) | Present only on LLM-inferred entries; set at infer time |

| Status | Condition | Runtime behaviour |
|--------|-----------|------------------|
| `validated` | Sheet listed in `validation_manifest.yaml`, PBI Desktop confirmed | Use directly, no warning |
| `generated` | Pipeline produced it; not in manifest (structurally valid, visually unverified) | Use + note in migration report |
| `inferred` | LLM-mapped with no sample | Use + explicit warning; entry written to suggestion artifact, not registry |

`status` values are **never downgraded**. Re-running `visual_agent.py` after adding manifest entries upgrades `generated` → `validated`.

---

## `samples/validation_manifest.yaml` Format

```yaml
workbooks:
  - file: input/simple_join_calculated_line_dashboard_multiple_visual_multiple_dashboard.twb
    validated_sheets:
      - "Sales Profit"
      - "Sales Profit CrossTab"
      - "Sales Year"
    validated_dashboards:
      - "Company Dashboard"

  - file: input/Superstore.twb
    validated_sheets:
      - "Overview"
      - "Shipping"
```

---

## Provenance Fields in `visual.json`

Added by `generator.py` during emission. Used by `visual_agent.py` for reliable pairing — not sheet display name.

```json
"_provenance": {
  "source_sheet_name":    "Sales Profit",
  "source_workbook_stem": "simple_join_calculated_line_dashboard",
  "source_visual_index":  1
}
```

These fields are stripped before PBIR validation (they are not part of the PBIR schema).

---

## `samples/visual_mappings.json` Schema

Five top-level sections. Each entry carries `status`, optional `score`, `source` (workbook + sheet), `schema_validated` flag, and `schema_ref`.

### 1. `mark_type_mapping`

Tableau mark type → PBI visual type. Replaces `MARK_TO_VISUAL` hardcode in P2.

```json
"mark_type_mapping": {
  "Bar":      { "pbi_visual_type": "barChart",    "status": "validated",
                "source": { "workbook": "simple_join_calculated_line_dashboard.twb", "sheet": "Sales Profit" } },
  "Column":   { "pbi_visual_type": "columnChart",  "status": "validated", "source": {...} },
  "Line":     { "pbi_visual_type": "lineChart",    "status": "validated", "source": {...} },
  "Area":     { "pbi_visual_type": "areaChart",    "status": "validated", "source": {...} },
  "Pie":      { "pbi_visual_type": "pieChart",     "status": "validated", "source": {...} },
  "Text":     { "pbi_visual_type": "tableEx",      "status": "validated", "source": {...} },
  "CrossTab": { "pbi_visual_type": "pivotTable",   "status": "validated", "source": {...} },
  "KPI":      { "pbi_visual_type": "cardVisual",   "status": "validated", "source": {...} },
  "Circle":   { "pbi_visual_type": "scatterChart", "status": "inferred",  "score": 0.7, "source": {...} },
  "Automatic":{ "pbi_visual_type": null, "use_inference_rules": true }
}
```

### 2. `automatic_inference_rules`

Shelf layout conditions → PBI visual type when Tableau mark is `Automatic`. These rules are **read-only** from the registry — the evaluation logic stays in `transformer.py:_infer_mark_type()`.

```json
"automatic_inference_rules": [
  {
    "id": "bar_from_automatic",
    "condition": { "row_shelf": "discrete_dimension", "col_shelf": "continuous_measure" },
    "pbi_visual_type": "barChart",
    "status": "validated",
    "source": { "workbook": "...", "sheet": "..." }
  },
  {
    "id": "line_from_automatic_date",
    "condition": { "col_shelf_has_date_part": true, "row_shelf": "continuous_measure" },
    "pbi_visual_type": "lineChart",
    "status": "validated",
    "source": { "workbook": "sql_custom_single_date.twb", "sheet": "Sheet 4" }
  },
  {
    "id": "kpi_from_automatic",
    "condition": { "row_shelf": "empty", "col_shelf": "empty", "encodings_text": "measure" },
    "pbi_visual_type": "cardVisual",
    "status": "validated",
    "source": { "workbook": "...", "sheet": "Total Sales By Year" }
  }
]
```

### 3. `visual_types`

Per-visual-type: query role mapping (layer 2) + object fragments (layer 3).

```json
"visual_types": {
  "barChart": {
    "query_roles": {
      "Category": { "tableau_shelf": "row",   "field_type": "dimension" },
      "Y":         { "tableau_shelf": "col",   "field_type": "measure"   },
      "Series":    { "tableau_shelf": "color", "field_type": "dimension", "optional": true }
    },
    "objects": {
      "labels": {
        "trigger": "show_data_labels == true",
        "pbi_json": { "labels": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}] },
        "schema_validated": true,
        "schema_ref": "fabric/item/report/definition/visualConfiguration/2.3.0/schema.json",
        "status": "validated",
        "source": { "workbook": "simple_join_calculated_line_dashboard.twb", "sheet": "Sales Profit" }
      }
    },
    "status": "validated",
    "source": { "workbook": "simple_join_calculated_line_dashboard.twb", "sheet": "Sales Profit" }
  },
  "pivotTable": {
    "query_roles": {
      "Columns": { "tableau_shelf": "col",               "field_type": "dimension" },
      "Values":  { "tableau_shelf": "crosstab_measures",  "field_type": "measure"  }
    },
    "objects": {
      "valuesOnRow": {
        "trigger": "crosstab_measures_non_empty AND row_fields_empty",
        "pbi_json": { "values": [{"properties": {"valuesOnRow": {"expr": {"Literal": {"Value": "true"}}}}}] },
        "schema_validated": true,
        "schema_ref": "fabric/item/report/definition/visualConfiguration/2.3.0/schema.json",
        "status": "validated",
        "source": {
          "workbook": "simple_join_calculated_line_dashboard_multiple_visual_multiple_dashboard.twb",
          "sheet": "Sales Profit CrossTab"
        }
      },
      "subTotals": {
        "trigger": "always",
        "pbi_json": { "subTotals": [{"properties": {
          "rowSubtotals":    {"expr": {"Literal": {"Value": "false"}}},
          "columnSubtotals": {"expr": {"Literal": {"Value": "false"}}}
        }}]},
        "schema_validated": true,
        "schema_ref": "fabric/item/report/definition/visualConfiguration/2.3.0/schema.json",
        "status": "validated",
        "source": {
          "workbook": "simple_join_calculated_line_dashboard_multiple_visual_multiple_dashboard.twb",
          "sheet": "Sales Profit CrossTab"
        }
      }
    },
    "status": "validated"
  }
}
```

### 4. `property_mappings`

Cross-cutting properties that apply across multiple visual types (layer 3).

```json
"property_mappings": {
  "show_data_labels": {
    "pbi_objects_key": "labels",
    "pbi_json": { "labels": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}] },
    "applicable_visual_types": ["barChart", "columnChart", "lineChart", "areaChart", "pieChart"],
    "excluded_visual_types":   ["tableEx", "pivotTable"],
    "schema_validated": true,
    "schema_ref": "fabric/item/report/definition/visualConfiguration/2.3.0/schema.json",
    "status": "validated"
  },
  "visual_title": {
    "pbi_key": "visualContainerObjects.title",
    "applicable_visual_types": ["*"],
    "schema_validated": true,
    "schema_ref": "fabric/item/report/definition/visualContainer/2.7.0/schema.json",
    "status": "validated"
  },
  "sort_definition": {
    "pbi_key": "query.sortDefinition",
    "applicable_visual_types": ["*"],
    "status": "validated"
  }
}
```

---

## `visual_agent.py` — Offline Builder Logic

Run: `uv run tab_to_pbi/visual_agent.py`

### Step 1 — Load manifest

Parse `samples/validation_manifest.yaml` → build `validated_lookup[stem][sheet/dashboard]`.

### Step 2 — Scan output pairs using provenance

For each workbook stem in `output/`:
- Load `output/<stem>.transformed.json`
- Walk `output/<stem>.Report/definition/pages/*/visuals/*/visual.json`
- **Match on `_provenance.source_sheet_name` and `_provenance.source_workbook_stem`** (not display name)
- Assign status: `validated` if sheet in manifest, else `generated`

When `_provenance` fields are absent (outputs generated before P2), fall back to sheet-name matching with a logged warning.

### Step 3 — Extract mappings using per-visual baselines

For each pair, diff the `visual.json` objects block against `samples/baselines/<visual_type>_minimal.json` — a curated minimal baseline for that visual type containing only the properties PBI always emits regardless of Tableau input.

Extract only **above-baseline** entries as candidate registry objects. This filters out PBI noise (default fonts, implicit grid lines, auto-generated formatting properties).

For each extracted `pbi_json` fragment: run `jsonschema.validate()` against the appropriate cached PBIR schema. Set `schema_validated: true` on pass.

Also extract from each pair:
- `mark_type_mapping` entry
- `automatic_inference_rules` entry (when mark_type is `Automatic`)
- `query_roles` for the visual type (layer 2)
- `property_mappings` entries — deduplicated cross-cutting properties

### Step 4 — Fill gaps with Claude (inferred only)

For any visual type in `MARK_TO_VISUAL` with no discovered sample:
- Use nearest validated sample (same visual family — e.g. `barChart` sample for `columnChart`; `tableEx` for `pivotTable` if pivotTable absent)
- Constrain Claude to PBIR `visualConfiguration/2.3.0` schema structure
- Store result as `status: "inferred", score: <float>`

### Step 5 — Write outputs

- Write `samples/visual_mappings.json` (full registry — **never written by runtime**)
- Regenerate `docs/visual_conversion.md` from registry — each row gets a `[validated]` / `[generated]` / `[inferred]` badge

### Re-run behaviour

- Safe and idempotent
- `validated` entries are never downgraded
- New manifest entries upgrade `generated` → `validated`
- LLM inference only runs for visual types still missing a sample

---

## `visual_mapper.py` — Thin Runtime Reader

**Scope: registry lookup only. Does not assemble visuals. Does not call Claude.**

```python
def load_registry() -> None:
    """Load samples/visual_mappings.json into module-level cache. Called once from main.py."""

def resolve_visual_type(mark_type: str) -> str | None:
    """Look up mark_type in registry mark_type_mapping. Returns None if absent."""

def resolve_object_fragments(visual_type: str, visual_info: dict) -> dict:
    """
    Return PBI objects fragments applicable to this visual based on triggers.
    Reads registry visual_types[visual_type].objects and property_mappings.
    Returns merged dict of applicable pbi_json fragments.
    """
```

`transformer.py` and `generator.py` call these functions. They remain responsible for all Tableau interpretation and PBIR assembly respectively. `visual_mapper.py` is a read-only lookup with no logic beyond trigger evaluation.

**Fallback:** if `samples/visual_mappings.json` is absent, both functions return `None` / empty dict and the pipeline uses existing hardcoded constants (`MARK_TO_VISUAL`, `_VISUAL_ROLES`, `_build_objects()`). This ensures fresh clones work before `visual_agent.py` has been run.

---

## Runtime Suggestion Artifact (P3 only)

When the runtime encounters a Tableau property with no registry entry, Claude is called with a tightly scoped prompt (grounded by nearest sample + PBIR schema). The result goes to:

```
output/<stem>.visual_mapping_suggestions.json
```

```json
{
  "workbook": "my_report.twb",
  "generated_at": "2026-05-13T...",
  "suggestions": [
    {
      "sheet": "Unknown Sheet",
      "visual_type": "barChart",
      "property": "custom_format",
      "pbi_json": { ... },
      "score": 0.82,
      "prompt_context": "...",
      "status": "pending_review"
    }
  ]
}
```

**This file is never read by the migration pipeline.** It is an advisory artifact for human review. After reviewing:
1. User adds the sheet to `validation_manifest.yaml`
2. User reruns `uv run tab_to_pbi/visual_agent.py`
3. Agent ingests the validated output and promotes to registry

The migration report references suggestions:
```json
"visual_mapping_suggestions": {
  "Unknown Sheet": {
    "property": "custom_format",
    "score": 0.82,
    "review_file": "output/my_report.visual_mapping_suggestions.json"
  }
}
```

---

## Schema Validation Scope

| What is validated | Schema used | Catches |
|-------------------|-------------|---------|
| `pbi_json` objects structure | `visualConfiguration/2.3.0` | Wrong `expr/Literal` shape, missing `properties` wrapper |
| `visualContainerObjects` | `visualContainer/2.7.0` | Malformed title/subtitle blocks |
| Formatting object values | `formattingObjectDefinitions/1.5.0` | Invalid formatting property types |
| Visual-type-specific property names | *(not in any schema)* | Cannot validate — caught only by PBI Desktop verification |

Schemas are read from `.pbir_schema_cache/` (already populated by the existing validator). No extra network calls.

---

## What `docs/visual_conversion.md` Becomes

No longer hand-edited. Regenerated by `visual_agent.py` from `visual_mappings.json`. Sections map directly:

| Registry section | Doc section |
|-----------------|-------------|
| `mark_type_mapping` | Visual Type Mapping table |
| `automatic_inference_rules` | Automatic Mark Type Inference table |
| `visual_types[*].query_roles` | queryState Role Mapping sections |
| `property_mappings` | Visual Properties Mapping table |

Each row gets a `[validated]` / `[generated]` / `[inferred]` badge. Rows marked `[inferred]` identify gaps needing PBI Desktop verification before next migration.

---

## Phased Implementation

### Phase 1 — Offline builder + doc regeneration (no pipeline changes)

- `samples/validation_manifest.yaml` seeded with known validated sheets
- `samples/baselines/<type>_minimal.json` curated for all 8 current visual types
- `visual_agent.py` implemented: scans output, extracts mappings, fills gaps with Claude, writes registry + doc
- `docs/visual_conversion.md` regenerated from registry
- Runtime pipeline **unchanged** — all existing hardcoded constants remain

### Phase 2 — Provenance + registry-backed lookups

- `generator.py` adds `_provenance` fields to every emitted `visual.json`
- `visual_mapper.py` implemented as thin reader
- `generator.py` consults registry for object fragments (falls back to `_build_objects()` if absent)
- `transformer.py` consults registry for mark type lookup (falls back to `MARK_TO_VISUAL` if absent)
- Existing code paths kept as fallback; no behaviour change on first run

### Phase 3 — Advisory suggestion mode

- Runtime unknown-property path calls Claude → `output/<stem>.visual_mapping_suggestions.json`
- `migration_report.json` gains `visual_mapping_suggestions` section
- `visual_agent.py` gains `--ingest-suggestions` flag to promote reviewed suggestions into registry

---

## Out of Scope

- Automatic PBI Desktop launch or UI automation
- Runtime registry mutation (any pipeline run that writes to `samples/visual_mappings.json`)
- Semantic normalization rules in the registry (`_infer_mark_type`, orientation flip)
- Custom/marketplace visual support
- Tableau Server API or PBI Service publishing
