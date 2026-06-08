# TabToPBI — Executive Summary

**Presented to:**  Key Stakeholders  
**Date:** May 2026  
**Status:** MVP Completes

---

## What We Built

**TabToPBI** is an automated migration tool that converts Tableau workbooks directly into Microsoft Power BI reports — with no manual rework required.

A user drops a Tableau file into a folder, runs one command, and receives a fully working Power BI report that opens in Power BI Desktop.

```
Input:   MyReport.twb  (Tableau workbook)
Output:  MyReport.Report/  (opens directly in Power BI Desktop)
         MyReport.migration_report.json  (what was migrated, what was flagged)
```

---

## The Problem We Are Solving

Organisations migrating from Tableau to Power BI face a significant manual effort:

- **Data models** must be rebuilt from scratch in Power BI's semantic model format
- **Calculated fields** written in Tableau's formula language must be rewritten in DAX (Power BI's query language) — a skill that requires deep expertise in both tools
- **Visuals, filters, sorts, and relationships** must be  recreated for every report
- For large estates (hundreds of workbooks), this migration can take months and requires specialist consultants

Our tool automates the bulk of this work.

---

## What the Tool Does Automatically

| Capability | Detail |
|---|---|
| **Data model migration** | Reads Tableau datasource definitions and generates a complete Power BI semantic model (tables, columns, data types, relationships) |
| **Formula translation** | Translates Tableau calculated fields to DAX using AI — including advanced LOD (Level of Detail) expressions |
| **Visual migration** | Maps Tableau chart types to Power BI equivalents (bar, column, line, area, pie, scatter, map, table) |
| **Filter migration** | Migrates categorical and range filters to Power BI visual-level filters |
| **Sort migration** | Migrates computed and alphabetic sorts |
| **Database connectivity** | Generates correct Power Query M connection code for Excel, CSV, PostgreSQL, Snowflake, Databricks, SQL Server, MySQL, and custom SQL |
| **DirectQuery support** | Live SQL connections are automatically detected and migrated as DirectQuery (no data import needed) |
| **Packaged workbooks** | `.twbx` files (Tableau packaged workbooks with embedded data) are fully supported |
| **Migration report** | Every run produces a JSON report listing what was translated, what was flagged as unsupported, and why |

---

## Where AI Adds Critical Value

The single hardest part of any Tableau → Power BI migration is **formula translation**.

Tableau and Power BI use completely different calculation languages. Simple field references, conditional logic, date functions, and aggregations all use different syntax. More critically, Tableau's **Level of Detail (LOD) expressions** — a core feature used in almost every non-trivial workbook — have no direct Power BI equivalent and require a semantic rewrite, not just a syntax substitution.

**Example:**

| Tableau formula | Translated DAX |
|---|---|
| `{FIXED [Order ID] : SUM([Profit])}` | `CALCULATE(SUM('orders'[profit]), ALLEXCEPT('orders', 'orders'[order_id]))` |
| `COUNTD([order_id]) - COUNTD([order_id (returns)])` | `DISTINCTCOUNT('orders'[order_id]) - DISTINCTCOUNT('returns'[order_id])` |
| `IF [Profit] > 0 THEN "Profitable" ELSE "Loss" END` | `IF(SUM('orders'[profit]) > 0, "Profitable", "Loss")` |

We use **Claude (Anthropic's AI model)** to perform this translation. Claude receives the formula along with the full table structure and column context, and returns the equivalent DAX expression. Fields that cannot be safely translated (Tableau Parameters, table calculations, cross-datasource references) are flagged as unsupported rather than silently mistranslated.

This is the part of the migration that would otherwise require a DAX specialist to do manually for every calculated field in every workbook.

---

## Databases Supported

| Database | Connection Mode |
|---|---|
| Excel / CSV | Import |
| PostgreSQL | Import + DirectQuery |
| Snowflake | Import + DirectQuery |
| Databricks | Import + DirectQuery |
| SQL Server | Import + DirectQuery |
| MySQL | Import + DirectQuery |
| Custom SQL (all SQL sources) | Import + DirectQuery |

---

## Verified Results

The tool has been tested end-to-end against real workbooks and verified in Power BI Desktop 2.152:

| Workbook | Complexity | Result |
|---|---|---|
| Simple Excel report | 1 table, 2 measures, filter | Opens and renders correctly |
| PostgreSQL with joins | 2 tables, INNER JOIN, 2 calc fields (cross-table) | Opens, both visuals render correctly |
| Three-table join | 3 tables, multi-sheet | Opens, all visuals render correctly |
| Superstore (enterprise sample) | 3 datasources, 21 calculated fields | 10 fields translated by AI, 11 flagged as unsupported — 0 pipeline errors |
| Packaged `.twbx` workbook | 3 datasources, 12 sheets | 0 pipeline errors |
| Snowflake live connection | DirectQuery mode | Verified |
| Databricks lakehouse | DirectQuery mode | Verified |

**120+ automated tests** cover the full pipeline. Every run is validated automatically before output is written.

---

## What Is Out of Scope (MVP)

The tool does not currently handle:

- Tableau Server API (publishing/downloading from Tableau Online)
- Data blending (sheets that combine multiple datasources)
- Full outer joins
- Tableau Parameters (flagged and reported, not translated)
- Table calculations (INDEX, SIZE, RANK — flagged and reported)
- Custom / extension visuals

These are explicit findings, not silent failures. Each unsupported item is written to the migration report with the reason.

---

## How It Works — The Pipeline

```
input/MyReport.twb (.twbx)
        │
        ▼
  ┌─────────────┐
  │  parser.py  │  Stage 1 — Parse
  └─────────────┘
        │
        │  Reads Tableau XML. Extracts:
        │  • Datasources: connection type, server, database, schema, tables
        │  • Columns: name, datatype, source table
        │  • Joins: type (INNER / LEFT / RIGHT), join keys
        │  • Relationships: logical-layer object-graph, cardinality signals
        │  • Calculated fields: formula, internal name, Tableau datatype
        │  • Sheets: mark type, shelf fields (rows/cols), filters, sorts
        │  • Unsupported patterns: data blending, full outer joins, Parameters
        │  • .twbx: unzips archive and locates embedded data files
        │
        ▼  workbook dict
  ┌─────────────────┐
  │ transformer.py  │  Stage 2 — Transform (deterministic + AI)
  └─────────────────┘
        │
        │  Deterministic mappings:
        │  • Connection type → Power Query M expression (Excel, CSV, PostgreSQL,
        │    Snowflake, Databricks, SQL Server, MySQL, custom SQL)
        │  • Live connection detected → sets storage_mode: directQuery
        │  • Mark type → PBI visual type (Bar→barChart, Line→lineChart, etc.)
        │  • Shelf aggregation prefix → DAX function (sum:→SUM, ctd:→DISTINCTCOUNT)
        │  • Aggregated shelf fields → named DAX measures written to TMDL
        │  • Joins + object-graph → PBI relationships with inferred cardinality
        │  • Filters → PBI filterConfig (categorical In, quantitative Between)
        │  • Sorts → PBI sortDefinition (computed by measure, alphabetic by column)
        │  • Column datatypes → explicit Power Query type cast (prevents text inference)
        │
        │  AI translation (Claude):
        │  • Replaces internal Calculation_xxx IDs with display names
        │  • Sends each calculated field formula + full table/column context to Claude
        │  • Receives DAX measure expression or UNSUPPORTED
        │  • Self-correction loop: detects bare column references, re-prompts Claude
        │  • DirectQuery blocklist: scans result for incompatible DAX functions
        │  • Translated measures written into semantic model; unsupported fields logged
        │
        ▼  transformed dict
  ┌──────────────┐
  │ generator.py │  Stage 3 — Generate PBIR
  └──────────────┘
        │
        │  Writes the complete PBIR folder structure:
        │
        │  MyReport.SemanticModel/
        │  ├── definition.pbism
        │  └── definition/
        │      ├── database.tmdl         (compatibility level, model name)
        │      ├── model.tmdl            (model-level settings, storage mode)
        │      ├── relationships.tmdl    (all table relationships)
        │      └── tables/
        │          └── <TableName>.tmdl  (columns, measures, Power Query M)
        │
        │  MyReport.Report/
        │  ├── definition.pbir
        │  └── definition/
        │      ├── version.json
        │      ├── report.json
        │      └── pages/
        │          ├── pages.json         (page order manifest)
        │          └── ReportSection1/
        │              ├── page.json
        │              └── visuals/
        │                  └── visual_1/
        │                      └── visual.json  (type, fields, filters, sorts, labels)
        │
        ▼  PBIR folder
  ┌──────────────┐
  │ validator.py │  Stage 4 — Validate
  └──────────────┘
        │
        │  Automatic checks before the user opens the file:
        │  • File presence: all required PBIR files exist
        │  • JSON schema: report.json and page.json validated against MS schemas
        │  • Semantic checks: visual field projections reference columns/measures
        │    that actually exist in the semantic model
        │  • Exits with error code 1 if any check fails — CI-friendly
        │
        ▼
  output/
  ├── MyReport.Report/              ← open directly in Power BI Desktop
  ├── MyReport.SemanticModel/
  └── MyReport.migration_report.json
      (translated fields, unsupported items, filters, table inventory,
       DirectQuery credential note)
```

---

## Key Technical Decisions

| Decision | Rationale |
|---|---|
| AI used only for formula translation | Everything else is deterministic — predictable, fast, no API cost |
| Two-layer DirectQuery safety | AI prompt constraint + static blocklist — neither alone is reliable enough |
| Explicit `UNSUPPORTED` sentinel | Mistranslated formulas that compile but produce wrong numbers are worse than flagged gaps |
| PBIR folder format (not .pbix) | Native format for Power BI Desktop 2.152+; editable; version-control friendly |
| Automated validator in the pipeline | Catches errors before the user opens the file, not after |

---

## What Comes Next

The MVP delivers a working migration pipeline for the supported workbook subset. Potential next steps include:

- **Tableau Parameter support** — translate Parameters to PBI Report Parameters or slicers
- **Table calculation support** — RANK, RUNNING_SUM, and window functions via DAX equivalents
- **Batch migration** — process an entire folder of workbooks in one run with a consolidated report
- **Tableau Server integration** — download workbooks directly from Tableau Online/Server via API
- **Power BI Service publish** — push migrated reports directly to a Power BI workspace

---

*Built with Python, Anthropic Claude API, and Microsoft PBIR format specification.*
