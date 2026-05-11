# Tableau → Power BI Visual & Property Conversion Reference

This document records validated Tableau-to-PBI mappings used by the migration pipeline.
Update this file whenever a new mapping is confirmed working in PBI Desktop.

---

## Visual Type Mapping

Tableau mark type → PBI `visualType` in `visual.json`.

| Tableau Mark Type | PBI Visual Type | Confidence | Notes |
|-------------------|-----------------|------------|-------|
| `Bar` | `barChart` | High | Horizontal bars; measure on Cols shelf |
| `Column` | `columnChart` | High | Vertical bars; measure on Rows shelf, or Bar + `mark_orientation="y"` |
| `Line` | `lineChart` | High | Line chart; date/category on X, measure on Y |
| `Area` | `areaChart` | High | Area chart; same shelf layout as Line |
| `Pie` | `pieChart` | High | Pie chart; dimension on Color shelf = legend slices |
| `Text` | `tableEx` | High | Cross-tab / text table |
| `KPI` *(internal)* | `cardVisual` | High | Single-number summary; both shelves empty, measure in `<encodings><text>` |
| `Automatic` | *(inferred)* | Medium | Inferred from shelf layout — see Automatic inference rules below |
| `Circle` | `scatterChart` | Medium | Scatter plot |
| `Shape` | `scatterChart` | Medium | Scatter plot with custom shapes |
| `Polygon` | `filledMap` | Medium | Filled map (geo polygons) |
| `Multipolygon` | `filledMap` | Medium | Filled map (multi-polygon geo data) |
| `PolyLine` | `map` | Medium | Line map |

### Automatic Mark Type Inference

When Tableau mark is `Automatic`, the pipeline infers the PBI visual type from shelf layout:

| Rows shelf | Cols shelf | `<encodings><text>` | Inferred PBI type |
|------------|------------|---------------------|-------------------|
| Discrete dimension | Continuous measure | — | `barChart` |
| Continuous measure | Date part (any — `yr`, `qr`, `mn`, `wk`, `hr`) | — | `lineChart` |
| Continuous measure | Continuous measure (non-date) | — | `lineChart` |
| Continuous measure | Discrete dimension (non-date) | — | `columnChart` |
| Neither continuous | Either | — | `tableEx` |
| *(empty)* | *(empty)* | Measure present | `cardVisual` (KPI) |

**Date-part rule:** Tableau treats any date derivation on the Cols shelf (ordinal or continuous) as a time axis, producing a Line chart under Automatic. The pipeline checks `date_part` on the parsed field dict — not `continuous` — to detect this case. Validated against `sql_custom_single_date.twb` Sheet 4 (`yr:order_date:ok` ordinal, `Automatic` mark) and `simple_join_calculated_line.twb` (explicit `Line` mark, same shelf layout).

The last row — both shelves empty, measure only in `<encodings><text>` — is Tableau's single-number KPI view. The parser reclassifies it as internal mark type `KPI` so the generator can map it to `cardVisual`.

---

## queryState Role Mapping

How Tableau shelves and encodings map to PBI `queryState` roles inside `visual.json`.

### Bar Chart (`barChart`)

| PBI Role | Tableau Source | Field type |
|----------|---------------|------------|
| `Category` | Rows shelf | Dimension |
| `Y` | Cols shelf | Measure |
| `Series` | Color shelf (dimension) | Dimension |

### Column Chart (`columnChart`)

| PBI Role | Tableau Source | Field type |
|----------|---------------|------------|
| `Category` | Cols shelf | Dimension |
| `Y` | Rows shelf | Measure |
| `Series` | Color shelf (dimension) | Dimension |

### Line Chart (`lineChart`) ✓ Validated

| PBI Role | Tableau Source | Field type |
|----------|---------------|------------|
| `Category` | Cols shelf | Dimension (often date) |
| `Y` | Rows shelf | Measure |
| `Series` | Color shelf (dimension) | Dimension — creates one line per value |

**Validated:** `Sales Year` sheet — `order_date Year` on Cols, `SUM(sales)` on Rows, `category` on Color → multiple lines, one per category.
**Validated:** `sql_custom_single_date.twb` Sheet 4 — `yr:order_date:ok` (ordinal YEAR, `Automatic` mark) on Cols, `SUM(sales)` on Rows → `lineChart`, `Category` bound to `order_date Year` derived column.

### Area Chart (`areaChart`)

| PBI Role | Tableau Source | Field type |
|----------|---------------|------------|
| `Category` | Cols shelf | Dimension |
| `Y` | Rows shelf | Measure |
| `Series` | Color shelf (dimension) | Dimension — creates stacked/overlapping areas |

### Pie Chart (`pieChart`) ✓ Validated

| PBI Role | Tableau Source | Field type |
|----------|---------------|------------|
| `Category` | `<encodings><color>` (dimension) | Dimension — legend slices |
| `Y` | `<encodings><wedge-size>` (primary) or `<encodings><text>` (fallback) | Measure |

**Encoding resolution for `Y` (slice size):**

Tableau serialises the Angle shelf as `<wedge-size>` when a measure is explicitly placed there. When no `<wedge-size>` exists the parser falls back to `<text>` encoding (measure placed on the Label shelf). This covers two Tableau pie-chart authoring patterns:

| Tableau authoring | XML present | Pie slices in PBI |
|-------------------|------------|-------------------|
| Measure on Angle shelf | `<wedge-size>` | Sized by that measure |
| Measure on Label shelf only (equal slices in Tableau) | `<text>` | Sized by the label measure |
| No measure at all | neither | `Y` role empty — no slices rendered |

**Validated:** `join_custom_rds_pie_map_dual.twb` — `Category` on Color, `SUM(Revenue)` on Angle (`<wedge-size>`) → `pieChart` with `Y = Sum Revenue`.
**Validated:** `simple_join_calculated_line_dashboard_multiple_visual.twb` `Sales Profit Pie Chart` — `Category` on Color, `Count(Orders)` on Label only (`<text>`, no `<wedge-size>`) → `pieChart` with `Y = Count orders` (text-encoding fallback).

### Scatter Chart (`scatterChart`)

| PBI Role | Tableau Source | Field type |
|----------|---------------|------------|
| `X` | Cols shelf | Measure |
| `Y` | Rows shelf | Measure |

### Filled Map (`filledMap`)

| PBI Role | Tableau Source | Field type |
|----------|---------------|------------|
| `Location` | Rows shelf | Dimension (geo field) |
| `Size` | Cols shelf | Measure / Dimension |

### Card / KPI (`cardVisual`) ✓ Validated

| PBI Role | Tableau Source | Field type |
|----------|---------------|------------|
| `Data` | `<encodings><text>` (single measure) | Measure |

**Detection:** Both `<rows>` and `<cols>` shelves are empty; measure is carried in `<encodings><text>` with mark `Automatic`. Parser sets `mark_type = "KPI"` and moves the field to `col_fields`.

**Validated:** `Total Sales By Year` sheet — `SUM(sales)` in text encoding, empty shelves → `cardVisual` with `Sum sales` measure in `Data` role.

### Table (`tableEx`) ✓ Validated

| PBI Role | Tableau Source | Field type |
|----------|---------------|------------|
| `Values` | All row + col fields combined | Any |

---

## Series Role Rules

The `Series` role splits a chart into multiple lines/bars (one per dimension value).

- **Supported visual types:** `lineChart`, `areaChart`, `columnChart`, `barChart`
- **Trigger:** Tableau dimension field on the **Color shelf** (`<encodings><color>`)
- **Excluded from Series:** Tableau calc fields, parameters, generated geo fields (Latitude, Longitude), and any field not present as a real datasource column
- **Projection structure:**

```json
"Series": {
  "projections": [
    {
      "field": {
        "Column": {
          "Expression": { "SourceRef": { "Entity": "<TableName>" } },
          "Property": "<FieldName>"
        }
      },
      "queryRef": "<TableName>.<FieldName>",
      "nativeQueryRef": "<FieldName>"
    }
  ]
}
```

Note: Series projections use `nativeQueryRef` (field name without table prefix). Category and Y projections use `active: true` instead.

---

## Aggregation Mapping

Tableau shelf aggregation prefix → DAX function used in auto-generated measures.

| Tableau prefix | DAX function | Measure name pattern |
|----------------|-------------|----------------------|
| `sum` | `SUM` | `Sum <FieldName>` |
| `avg` / `average` | `AVERAGE` | `Avg <FieldName>` |
| `cntd` / `ctd` | `DISTINCTCOUNT` | `Count Distinct <FieldName>` |
| `cnt` | `COUNTA` | `Count <FieldName>` |
| `min` | `MIN` | `Min <FieldName>` |
| `max` | `MAX` | `Max <FieldName>` |
| `median` | `MEDIAN` | `Median <FieldName>` |
| `var` | `VAR.S` | `Var <FieldName>` |
| `varp` | `VAR.P` | `VarP <FieldName>` |
| `stdev` | `STDEV.S` | `StDev <FieldName>` |
| `stdevp` | `STDEV.P` | `StDevP <FieldName>` |

---

## Data Type Mapping

Tableau column `datatype` → PBI TMDL `dataType`.

| Tableau datatype | PBI dataType | Power Query M type |
|------------------|--------------|--------------------|
| `string` | `string` | `type text` |
| `integer` | `int64` | `Int64.Type` |
| `real` | `double` | `Decimal.Type` |
| `date` | `dateTime` | `type datetime` |
| `datetime` | `dateTime` | `type datetime` |
| `boolean` | `boolean` | `type logical` |

---

## Date Part Mapping

Tableau date derivation prefix → PBI column naming and Power Query M expression.

| Tableau prefix | PBI derived column name | Power Query M (Import) |
|----------------|------------------------|------------------------|
| `yr` | `<Field> Year` | `Date.Year([#"<Field>"])` |
| `qr` | `<Field> Quarter` | `Date.QuarterOfYear([#"<Field>"])` |
| `mn` | `<Field> Month` | `Date.Month([#"<Field>"])` |
| `wk` | `<Field> Weeknum` | `Date.WeekOfYear([#"<Field>"])` |
| `dy` | `<Field> Day` | `Date.Day([#"<Field>"])` |
| `hr` | `<Field> Hour` | `Time.Hour([#"<Field>"])` |

In PBI visual `queryState`, the derived column name (e.g. `order_date Year`) is used as the `Property` with `Column` field type.

---

## Filter Mapping

Tableau filter class → PBI `filterConfig` filter type.

| Tableau filter class | PBI filter type | Operator |
|----------------------|-----------------|----------|
| `categorical` (values listed) | `Categorical` | `In` |
| `categorical` (no values) | *(skipped — context/action filter)* | — |
| `quantitative` (min + max) | `Advanced` | `Between` |
| `quantitative` (min only) | `Advanced` | `GreaterThanOrEqual` |
| `quantitative` (max only) | `Advanced` | `LessThanOrEqual` |

Filters are written to `filterConfig` on the visual container (visual-level filters) or to `report.json` (datasource-level / report-level filters).

---

## Visual Properties Mapping

| Tableau property | PBI location | PBI structure |
|------------------|-------------|---------------|
| Data labels on (`mark-labels-show=true`) | `visual.objects.labels` | `[{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}]` |
| Sheet title | `visual.visualContainerObjects.title` | `show: true`, `text: '<title>'` |
| Computed sort (by measure) | `visual.query.sortDefinition` | `Measure` field expression + `direction` |
| Natural / alphabetic sort (by dimension) | `visual.query.sortDefinition` | `Column` field expression + `direction` |
| Manual sort | *(unsupported — skipped)* | — |

---

## Datasource / Connection Mapping

| Tableau connection type | PBI storage mode | Power Query M connector |
|------------------------|-----------------|------------------------|
| `excel-direct` / `textscan` (with extract) | Import | `Excel.Workbook(File.Contents(...))` / `Csv.Document(File.Contents(...))` |
| `postgres` (with extract) | Import | `PostgreSQL.Database(server, database)` |
| `postgres` (live, no extract) | DirectQuery | `PostgreSQL.Database(server, database)` |
| `sqlserver` | Import / DirectQuery | `Sql.Database(server, database)` |
| `mysql` | Import / DirectQuery | `MySQL.Database(server, database)` |
| `redshift` | Import / DirectQuery | `AmazonRedshift.Database(server, database)` |
| `snowflake` | Import / DirectQuery | `Snowflake.Databases(server)` |
| `oracle` | Import / DirectQuery | `Oracle.Database(server)` |
| `bigquery` | Import / DirectQuery | `GoogleBigQuery.Database()` |

Custom SQL (`<relation type="text">`) is wrapped in `Value.NativeQuery()` for SQL-capable sources.

---

## Relationship Mapping

| Tableau relationship source | PBI TMDL structure |
|----------------------------|--------------------|
| Logical-layer (`object-graph`) — unique key on first side | `fromColumn` = many side, `toColumn` = one side |
| Logical-layer — unique key on second side | `fromColumn` = first, `toColumn` = second (one side) |
| Logical-layer — no unique key | many-to-many, `crossFilteringBehavior: bothDirections` |
| Physical-layer LEFT JOIN | one-to-many (from = one/preserved side) |
| Physical-layer INNER JOIN | one-to-many (naming convention signals used) |
| Physical-layer FULL OUTER JOIN | one-to-many (naming convention signals) |
| Physical-layer RIGHT JOIN | Rewritten as LEFT JOIN with sides flipped |

Relationships are written exclusively to `relationships.tmdl` (not inline in `model.tmdl`).

---

## Unsupported Patterns (logged to migration_report.json)

| Tableau feature | Status | Notes |
|-----------------|--------|-------|
| LOD expressions (`{FIXED}`, `{INCLUDE}`, `{EXCLUDE}`) | AI-translated | Via Claude prompt |
| Table calculations | Unsupported | No DAX equivalent |
| Parameters | Unsupported | Not migrated |
| Data blending (multiple datasources per sheet) | Unsupported | Flagged in report |
| FULL OUTER joins (non-equi) | Unsupported | Flagged in report |
| Custom SQL on non-SQL sources | Unsupported | Flagged in report |
| Tableau-generated geo fields (Latitude, Longitude) | Unsupported | Skipped from visual projections |
| `Heatmap`, `GanttBar`, `VizExtension` marks | Fallback to `tableEx` | Warning in report |
| Manual sort | Skipped | Warning in report |
| Cross-datasource calc fields | Unsupported | Flagged by translator |
