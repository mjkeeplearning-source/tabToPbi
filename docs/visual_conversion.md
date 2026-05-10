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
| `Automatic` | *(inferred)* | Medium | Inferred from shelf layout — see Automatic inference rules below |
| `Circle` | `scatterChart` | Medium | Scatter plot |
| `Shape` | `scatterChart` | Medium | Scatter plot with custom shapes |
| `Polygon` | `filledMap` | Medium | Filled map (geo polygons) |
| `Multipolygon` | `filledMap` | Medium | Filled map (multi-polygon geo data) |
| `PolyLine` | `map` | Medium | Line map |

### Automatic Mark Type Inference

When Tableau mark is `Automatic`, the pipeline infers the PBI visual type from shelf layout:

| Rows shelf | Cols shelf | Inferred PBI type |
|------------|------------|-------------------|
| Continuous measure | Discrete dimension | `columnChart` |
| Discrete dimension | Continuous measure | `barChart` |
| Continuous measure | Continuous measure | `lineChart` |
| Neither continuous | Either | `tableEx` |

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

### Area Chart (`areaChart`)

| PBI Role | Tableau Source | Field type |
|----------|---------------|------------|
| `Category` | Cols shelf | Dimension |
| `Y` | Rows shelf | Measure |
| `Series` | Color shelf (dimension) | Dimension — creates stacked/overlapping areas |

### Pie Chart (`pieChart`) ✓ Validated

| PBI Role | Tableau Source | Field type |
|----------|---------------|------------|
| `Category` | Color shelf (dimension via `color_enc_fields`) | Dimension — legend slices |
| `Y` | Wedge-size encoding (`wedge-size`) | Measure |

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
