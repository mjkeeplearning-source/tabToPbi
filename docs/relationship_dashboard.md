# Dashboard Relationship & Filter Direction — Research Notes

## Problem Statement

When a Tableau dashboard filter (slicer) is migrated to PBI, filtering does not propagate
to chart visuals that query the related table, even when a PBI relationship exists between
the two tables.

Confirmed on: `simple_join_calculated_line_dashboard.twb`
- Slicer on `people.region` does not filter bar chart (`orders` measures/dimensions)

---

## Root Cause 1: NoFilter Interaction (Line Chart)

The line chart (`Sales  Year`) receives an explicit `NoFilter` visual interaction,
preventing the slicer from affecting it at all.

**Why it was generated:**

`transform_dashboards` in `dashboard.py` adds a `NoFilter` interaction whenever the
slicer's anchor sheet (the `name` attribute on the filter zone) differs from a chart's
source sheet:

```python
if c["source_sheet"] != s["scoped_to_sheet"]   # flawed condition
```

**Why this is wrong:**

The filter zone `name` attribute is the sheet the filter was _dragged from_ in the
Tableau dashboard builder — it is not a scope restriction. Tableau's default dashboard
filter behavior is "All worksheets using this data source." A scope restriction would
appear as a `<filter-policy>` element, which this workbook does not have.

**Fix:** Do not generate `NoFilter` interactions unless explicit scope-restriction XML
(`<filter-policy>`) is parsed from the Tableau workbook.

---

## Root Cause 2: Inverted Relationship Direction (Bar Chart)

The bar chart has no `NoFilter` interaction, but the slicer still does not filter it.

### Official PBI documentation — TMSL crossFilteringBehavior

Source: [Relationships object (TMSL) — Microsoft Learn](https://learn.microsoft.com/en-us/analysis-services/tmsl/relationships-object-tmsl?view=sql-analysis-services-2025)

> **OneDirection (default):**
> _"The rows selected in the 'To' end of the relationship will automatically filter
> scans of the table in the 'From' end of the relationship."_

Filter travels: **TO end → FROM end**

Source: [Model relationships in Power BI Desktop — Microsoft Learn](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-relationships-understand)

> _"For one-to-many relationships, the cross filter direction is always from the 'one' side."_
> _"The 'one' side means the column contains unique values."_

### Our generated TMDL

```
relationship 'people_region -> orders_region'
    fromColumn: people.region     ← FROM end (gets filtered)
    toColumn:   orders.region     ← TO end   (filter origin)
```

Applying the official rule:

| TMDL property | Our value | Official meaning |
|---|---|---|
| `fromColumn` | `people.region` | FROM end — what gets filtered |
| `toColumn` | `orders.region` | TO end — where filter originates |

Filter flows: `orders` (TO) → `people` (FROM)

### Why the slicer fails

1. User selects "East" in `people.region` slicer
2. PBI filters the `people` table: `people.region = 'East'`
3. PBI checks the relationship for propagation
4. Relationship arrow points TO→FROM = `orders` → `people`
5. `people` is the FROM/downstream end — no further propagation possible
6. `orders` is upstream (TO end) — unreachable with single-direction filtering
7. Bar chart (querying `orders`) sees no filter change

### Real-world cardinality vs generated TMDL

| | Semantic reality | Our TMDL |
|---|---|---|
| `people` (4 rows, 1 per region) | ONE side — filter should originate here | FROM end (filter target) — WRONG |
| `orders` (1000s of rows) | MANY side — should be filtered | TO end (filter origin) — WRONG |

The correct TMDL should be:
```
fromColumn: orders.region     ← MANY side (fact, gets filtered)
toColumn:   people.region     ← ONE side  (dimension, filter origin)
```

---

## Why Regular Sheet Pages Work Despite the Inverted Relationship

The `ReportSection1` bar chart filter is written as a `filterConfig` in `visual.json`:

```json
"filterConfig": {
  "filters": [{
    "field": { "Column": { "Entity": "orders", "Property": "region" } },
    "filter": { "Where": [{ "Condition": { "In": { "Values": ["East", ...] } } }] }
  }]
}
```

This is a **hardcoded WHERE clause on the visual's own query** against `orders` directly.
No relationship traversal occurs. The inverted relationship is completely bypassed.

The relationship direction bug was always present but invisible — it only surfaced when
the dashboard slicer required live cross-filtering at runtime.

---

## Why Filter-Based Cardinality Inference Is Not Robust

### Proposal evaluated

"Use the Tableau dashboard filter's datasource reference to determine which table is the
ONE side (toColumn in PBI)."

### Why it fails — based on official documentation

**Finding 1: Tableau's official XSD does not store cardinality as an attribute**

Source: [tableau/tableau-document-schemas — GitHub (twb_2026.1.0.xsd)](https://github.com/tableau/tableau-document-schemas)

The official XSD defines relationship endpoints as:

```xml
<xs:element name="relationship">
  <xs:complexType>
    <xs:sequence>
      <xs:group ref="SQLExpression-G"/>
      <xs:group ref="EndPointAttributes-G"/>
    </xs:sequence>
  </xs:complexType>
</xs:element>
```

`EndPointAttributes-G` attributes on each endpoint:

| Attribute | Required | Meaning |
|---|---|---|
| `object-id` | Required | Which table |
| `unique-key` | Optional | This side has unique values (= ONE side) |
| `guaranteed-value` | Optional | Referential integrity hint |
| `is-db-set-unique-key` | Optional | DB-enforced uniqueness |
| `is-db-set-guaranteed-value` | Optional | DB-enforced RI |

No explicit `cardinality` attribute exists anywhere in the schema. Cardinality is
encoded only through `unique-key`, and only when the user has explicitly set it.

**Finding 2: Tableau's default cardinality is Many-to-Many**

Source: [Optimize Relationship Queries — Tableau Help](https://help.tableau.com/current/server/en-us/datasource_relationships_perfoptions.htm)

> _"The default settings are: Cardinality: Many-to-Many, Referential integrity: Some Records Match."_

When `unique-key` is absent (the default), Tableau treats the relationship as M:M.
Our actual workbook has no `unique-key` set on either endpoint:

```xml
<relationship>
  <expression op='='>
    <expression op='[region]' />
    <expression op='[region (orders)]' />
  </expression>
  <first-end-point object-id='people (superstore.people)_...' />
  <second-end-point object-id='orders (superstore.orders)_...' />
</relationship>
```

No cardinality signal is present at all.

**Finding 3: Dashboard filter placement does not indicate cardinality**

A filter on a field means the user chose to filter by that field — nothing more. There
is no official Tableau documentation linking filter placement to relationship cardinality.
Counterexamples that break filter-based inference:

| Case | Filter on | True ONE side | Inference result |
|---|---|---|---|
| Filter on fact table | `orders.customer_name` | `customers` (dim) | Wrong — would set orders as ONE |
| No dashboard filter | — | Unknown | No signal at all |
| Filters on both tables | `people.region` AND `orders.ship_mode` | `people` | Conflicting signals |

---

## Correct Robust Approach

Based entirely on official documentation:

| Signal | Reliability | Source |
|---|---|---|
| `unique-key="true"` on Tableau endpoint | **High** — directly means ONE side → `toColumn` in PBI | Official Tableau XSD |
| `unique-key` absent (M:M default) | **No signal** | Tableau perf options doc |
| Dashboard filter datasource | **Unreliable** — user filter choice, not cardinality | No official doc links these |
| Distinct value count from DB | **High** — fewer unique values = ONE side | Data-derived |

**Implementation priority:**

1. Parse `unique-key` from `<first-end-point>` / `<second-end-point>` in Tableau XML.
   If `unique-key="true"`, that endpoint is the ONE side → becomes `toColumn` in PBI TMDL.
2. When `unique-key` is absent (default M:M): write `crossFilteringBehavior: bothDirections`
   in TMDL. This matches Tableau's M:M default semantics. PBI docs note this has a
   performance cost and can cause ambiguity — flag in migration report.
3. Flag all relationships without explicit `unique-key` in `migration_report.json` with a
   note: "Cardinality not set in Tableau source — defaulted to bidirectional cross-filter.
   Verify cardinality in PBI Desktop model view."

---

## Sources

- [Relationships object (TMSL) — Microsoft Learn](https://learn.microsoft.com/en-us/analysis-services/tmsl/relationships-object-tmsl?view=sql-analysis-services-2025)
- [Model relationships in Power BI Desktop — Microsoft Learn](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-relationships-understand)
- [Object definitions in TMDL — Microsoft Learn](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-reference-tabular-object?view=sql-analysis-services-2025)
- [One-to-one relationship guidance — Microsoft Learn](https://learn.microsoft.com/en-us/power-bi/guidance/relationships-one-to-one)
- [Tableau Document Schemas — GitHub (official XSD)](https://github.com/tableau/tableau-document-schemas)
- [Cardinality and Referential Integrity — Tableau Help](https://help.tableau.com/current/pro/desktop/en-us/cardinality_and_ri.htm)
- [Optimize Relationship Queries — Tableau Help](https://help.tableau.com/current/server/en-us/datasource_relationships_perfoptions.htm)

---

## Implementation

**Date:** 2026-05-09  
**Branch:** dashboard

Both root causes were fixed with TDD (tests written first, watched fail, then implemented).
All 10 new tests pass; no regressions in the existing suite.

---

### Root Cause 1 — Implemented fix

**File:** `tab_to_pbi/dashboard.py`

Removed the `source_sheet != scoped_to_sheet` condition that generated `NoFilter` interactions
based on the filter zone `name` attribute. Replaced with a `filter_policy_sheets` check:

```python
interactions = [
    {"source": s["visual_id"], "target": c["visual_id"], "type": "NoFilter"}
    for s in slicer_visuals
    for c in chart_visuals
    if s.get("filter_policy_sheets") and c["source_sheet"] not in s["filter_policy_sheets"]
]
```

`filter_policy_sheets` is a list populated by the parser only when an explicit `<filter-policy>`
element is found in the Tableau XML. Without that element, the list is absent and no `NoFilter`
is generated — matching Tableau's documented default ("all worksheets using this data source").

The slicer visual dict creation in `transform_dashboards` was also updated to forward
`filter_policy_sheets` from the zone dict when present.

**New tests:** `test_no_nofilter_when_sheets_differ_without_filter_policy`,
`test_transform_nofilter_only_when_filter_policy_present` in `tests/test_dashboard.py`.

---

### Root Cause 2 — Implemented fix

**Files:** `tab_to_pbi/parser.py`, `tab_to_pbi/transformer.py`, `tab_to_pbi/generator.py`

#### parser.py — `_parse_relationships`

Reads `unique-key` attribute from `<first-end-point>` and `<second-end-point>` and adds two
boolean flags to each logical relationship dict:

```python
first_ep = rel.find("first-end-point")
second_ep = rel.find("second-end-point")
first_unique  = first_ep  is not None and first_ep.get("unique-key")  == "true"
second_unique = second_ep is not None and second_ep.get("unique-key") == "true"

rels.append({
    ...,
    "first_unique_key":  first_unique,
    "second_unique_key": second_unique,
})
```

#### transformer.py — `_map_relationship`

Uses the flags for four exhaustive cases covering every possible state of the `unique-key`
attribute (per official Tableau XSD):

| `first_unique_key` | `second_unique_key` | Action | TMDL result |
|---|---|---|---|
| `False` | `True` | Second is ONE — keep order | `toColumn` = second (ONE), default many:one |
| `True` | `False` | First is ONE — swap | `toColumn` = first (ONE), default many:one |
| `True` | `True` | Both unique — 1:1 | `fromCardinality: one`, `toCardinality: one` |
| `False` | `False` | No signal — Tableau M:M default | `fromCardinality: many`, `toCardinality: many` |

For the swap case, `from_table`/`from_column` and `to_table`/`to_column` are physically
exchanged so the generator receives them in the correct PBI-convention order without any
further special-casing.

#### generator.py — `_write_tmdl_model`

Extended the `crossFilteringBehavior: bothDirections` condition to cover both 1:1 and M:M:

```python
if (from_card, to_card) in (("one", "one"), ("many", "many")):
    lines.append("\tcrossFilteringBehavior: bothDirections")
```

- **1:1**: Microsoft documentation states cross-filter direction is always Both for one-to-one
  relationships — it is the only valid option.
- **M:M**: Matches Tableau's documented M:M default, where filtering propagates from either side.

#### 1:1 relationship — additional note

Per [Microsoft's one-to-one guidance](https://learn.microsoft.com/en-us/power-bi/guidance/relationships-one-to-one),
1:1 relationships are a model design smell. When one is detected (both endpoints `unique-key`),
the migration report flags it: *"One-to-one relationship detected. Microsoft recommends merging
these tables in Power Query instead."* This mirrors the official guidance without attempting an
automatic merge, which would require intent the tool does not have.

**New tests in `tests/test_t12.py`:**
- `test_parse_logical_relationship_no_unique_key`
- `test_parse_logical_relationship_second_unique_key`
- `test_parse_logical_relationship_first_unique_key`
- `test_parse_logical_relationship_both_unique_key`
- `test_map_logical_relationship_second_unique_key_keeps_order`
- `test_map_logical_relationship_first_unique_key_swaps`
- `test_map_logical_relationship_no_unique_key_mm_cardinality`
- `test_map_logical_relationship_both_unique_key_one_to_one`
- `test_generator_mm_relationship_writes_both_directions`
