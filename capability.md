# Tableau → Power BI Migration: Capability Summary

**Product:** TabToPBI — automated file-based Tableau workbook migration to Microsoft Power BI  
**Status:** MVP complete and verified in Power BI Desktop 2.152

---

## What It Does

TabToPBI reads a Tableau workbook (`.twb` or `.twbx`), automatically migrates its data model, visuals, relationships, calculated fields, filters, and sorts into a valid **PBIR folder** that opens directly in Power BI Desktop — no manual repair required.

```
input/MyReport.twb  →  [pipeline]  →  output/MyReport.Report/   (opens in PBI Desktop)
                                       output/MyReport.SemanticModel/
                                       output/MyReport.migration_report.json
```

---

## AI Integration

| Role | How Claude Is Used |
|------|-------------------|
| **Formula translation** | Tableau calculated field formulas are sent to Claude (`claude-opus-4-7`) for translation to DAX measures |
| **LOD expression mapping** | Level-of-Detail expressions (`{FIXED}`, `{INCLUDE}`, `{EXCLUDE}`) mapped to `CALCULATE + ALLEXCEPT / VALUES / ALL` |
| **Cross-table formula resolution** | Claude receives column context from all related tables to resolve cross-table references correctly |
| **DirectQuery safety** | When source is live SQL, Claude is prompted to restrict output to DirectQuery-compatible DAX; a deterministic blocklist catches anything that slips through |
| **Unsupported detection** | Claude returns `UNSUPPORTED` for Parameters, table calculations, and cross-datasource formulas; these are excluded from the model and logged in the migration report |

Everything else (visual mapping, join parsing, relationship writing, M expressions, aggregations) is **deterministic** — AI is used only where formula semantics require it.

---

## Databases Tested

| Database | Connector | Mode | Status |
|----------|-----------|------|--------|
| Excel (`.xlsx`) | `Excel.Workbook` | Import | Verified in PBI Desktop |
| CSV | `Csv.Document` | Import | Verified in PBI Desktop |
| PostgreSQL (AWS RDS) | `PostgreSQL.Database` | Import + DirectQuery | Verified |
| Snowflake | `Snowflake.Databases` | Import + DirectQuery | Verified |
| Databricks | `Databricks.Catalogs` | Import + DirectQuery | Verified |
| SQL Server | `Sql.Database` | Import + DirectQuery | Supported |
| MySQL | `MySQL.Database` | Import + DirectQuery | Supported |
| Custom SQL | `Value.NativeQuery()` | Import + DirectQuery | Verified (PostgreSQL, Snowflake) |

**DirectQuery mode** is auto-detected: live connections (no extract) generate DirectQuery PBIR automatically.

---

## Joins & Relationships

| Pattern | Support | Notes |
|---------|---------|-------|
| INNER JOIN | Full | Mapped to PBI relationship |
| LEFT OUTER JOIN | Full | Mapped to PBI relationship |
| RIGHT OUTER JOIN | Full | Flipped to LEFT for PBI compatibility |
| FULL OUTER JOIN | Detected, flagged | Written to migration report as unsupported |
| Tableau logical-layer relationships (object-graph) | Full | Explicit key columns extracted |
| Custom SQL joins | Full | Wrapped in `Value.NativeQuery()` |
| Cross-source relationships | Detected, flagged | Same-source constraint enforced |
| Data blending (multi-datasource sheets) | Detected, flagged | Logged as unsupported |

Relationships are written to `relationships.tmdl` as standalone objects, matching PBI Desktop's own save format exactly.

---

## Visual Types Tested

| Tableau Mark | Power BI Visual | Confidence | Tested |
|---|---|---|---|
| Bar | `barChart` | High | Yes |
| Column (Bar + orientation=Y) | `columnChart` | High | Yes |
| Line | `lineChart` | High | Yes |
| Area | `areaChart` | High | Yes |
| Pie | `pieChart` | High | Yes |
| Circle / Shape | `scatterChart` | Medium | Yes |
| Polygon / Multipolygon | `filledMap` | Medium | Yes |
| PolyLine | `map` | Medium | Yes |
| Text / Automatic | `tableEx` | High | Yes |

**Multi-measure sheets:** when Tableau places two measures on the same axis (side-by-side panels), the pipeline emits one PBI visual per measure on the same page.

---

## Features Implemented & Tested

### Aggregations → DAX Measures
Tableau shelf prefix codes are decoded into named DAX measures written directly to TMDL:

| Tableau Prefix | DAX Function |
|---|---|
| `SUM` | `SUM` |
| `CNTD` / `CTD` | `DISTINCTCOUNT` |
| `CNT` | `COUNTA` |
| `AVG` | `AVERAGE` |
| `MIN` / `MAX` | `MIN` / `MAX` |
| `MEDIAN` | `MEDIAN` |

### Filters
- **Categorical filters** (IN list) → PBI `filterConfig` with `In` operator
- **Quantitative / range filters** → `Between` or `Comparison` operators
- **Date filters** → correct datetime literal formatting
- Filters written to visual-level `filterConfig` in `visual.json`

### Sorting
- **Computed sort** (by measure) → PBI `sortDefinition` using `Measure` field expression
- **Natural / alphabetic sort** → `Column` field expression
- **Multi-sort arrays** supported
- **Manual sort** detected and logged as unsupported
- Computed sorts referencing untranslated fields pruned with warning

### Data Labels
- Tableau `mark-labels-show` → PBI `objects.labels` in `visual.json`
- Applied to bar, column, line, area, pie, scatter, map visuals
- Skipped for table (`tableEx`) visuals

### Calculated Fields → DAX
- Translated via Claude with per-table column context
- Internal Tableau calc IDs (`Calculation_xxx`) resolved to display names before sending to Claude
- LOD expressions fully supported
- Unsupported fields (Parameters, table calcs) excluded from TMDL and logged

### Column Type Casting
- Tableau column `datatype` metadata used to generate explicit `Table.TransformColumnTypes` in Power Query M
- Prevents PBI Desktop from misclassifying numeric columns as text at load time

---

## Workbooks Tested

### 1. `simple.twb` — Excel, Single Table
- **Data:** Excel (`Orders` table)
- **Visuals:** Column chart (Category × DISTINCTCOUNT(Product ID) + SUM(Sales))
- **Features tested:** Multi-measure compound shelf, column type casting, categorical filter
- **PBI result:** Opens and renders correctly ✓

### 2. `simple_join.twb` — PostgreSQL, Two Tables
- **Data:** PostgreSQL — `orders` + `returns` tables, INNER JOIN on `order_id`
- **Visuals:** Column chart (DeltaOrder), Bar chart (Margin)
- **Calc fields:** `DeltaOrder` (`COUNTD([order_id]) - COUNTD([order_id (returns)])`) → DAX `DISTINCTCOUNT` via Claude; `Margin` → DAX `DIVIDE`
- **Features tested:** Multi-table join, relationship, cross-table formula translation
- **PBI result:** Opens, both visuals render correctly ✓

### 3. `simple_join_calculated_line.twb` — PostgreSQL, Three Tables
- **Data:** PostgreSQL — `people` + `orders` + `returns`
- **Visuals:** Column chart + Line chart (two sheets)
- **Features tested:** Three-table join generalisation, multi-sheet migration
- **PBI result:** Opens, both visuals render correctly ✓

### 4. `Superstore.twb` — Excel, Three Datasources, 21 Calc Fields
- **Data:** Excel (Sales Target, Sample - Superstore, Sales Commission)
- **Visuals:** Multiple sheets across 3 datasources
- **Calc fields:** 21 total — 10 translated by Claude (including LOD, conditional logic), 11 logged as unsupported (Parameters, cross-datasource)
- **Features tested:** Multi-datasource, LOD expressions, calc name substitution, DirectQuery safety blocklist
- **PBI result:** 0 pipeline errors ✓

### 5. `tabpbi.twbx` — Packaged Workbook
- **Data:** `.twbx` archive with embedded data files (3 datasources, 12 sheets)
- **Features tested:** Archive extraction, embedded file path resolution, multi-sheet generation
- **PBI result:** 0 pipeline errors ✓

### 6. `join_custom_rds_pie_map_dual.twb` — PostgreSQL, Custom SQL, Pie + Map
- **Data:** PostgreSQL with custom SQL subquery + standard joins
- **Visuals:** Pie chart, filled map, dual-axis
- **Features tested:** `Value.NativeQuery()` custom SQL, pie and map visual types
- **PBI result:** Verified ✓

### 7. `snowflake.twb` — Snowflake
- **Data:** Snowflake cloud warehouse
- **Features tested:** Snowflake connector, DirectQuery mode auto-detection
- **PBI result:** Verified ✓

### 8. `daatabricks.twb` — Databricks
- **Data:** Databricks lakehouse
- **Features tested:** Databricks connector, dynamic sheet handling
- **PBI result:** Verified ✓

---

## Migration Report

Every run produces `migration_report.json` containing:
- **Translated fields** — DAX expression, source formula, table scope
- **Unsupported items** — reason logged (Parameter, table calc, cross-datasource, unsupported join type)
- **Sheet filters** — each visual-level filter migrated
- **Table inventory** — all physical tables, columns, storage mode
- **DirectQuery credential note** — user is instructed to enter credentials on first PBI Desktop open

---

## Validation

An automated PBIR validator runs at the end of every pipeline execution:
- **File presence checks** — all required PBIR files exist
- **JSON schema validation** — report and page files validated against Microsoft schemas
- **Semantic cross-reference checks** — visual projections reference fields that exist in the semantic model
- **Exit code 1 on errors** — CI-friendly; warnings for schema versions not publicly published by Microsoft

**Test suite: 120+ automated tests** covering parser, transformer, generator, validator, translator, and end-to-end pipeline across all 5 primary workbooks.
