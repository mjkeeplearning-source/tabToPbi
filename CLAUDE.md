# Tableau to Power BI Migration Automation

## Project Overview

MVP automate file-based migration of Tableau workbooks to Microsoft Power BI using Python, PBIR folder generation, and Anthropic AI for narrow formula translation tasks.

This MVP is intentionally constrained. The goal is to produce a valid PBIR output that opens in Power BI Desktop for a supported subset of Tableau workbooks, not to solve every Tableau migration pattern in the first release.


## VERY IMPORTANT

- Be simple. Approach tasks in a simple, incremental way.
- Work incrementally ALWAYS. Small, simple steps. Validate and check each increment before moving on.
- Use LATEST apis as of NOW.

## MANDATORY Code Style

- Do not overengineer. Do not program defensively. Use exception managers only when needed.
- Identify root cause before fixing issues. Prove with evidence, then fix.
- Work incrementally with small steps. Validate each increment.
- Use latest library APIs.
- Use `uv` as Python package manager. Always `uv run xxx`, never `python3 xxx`, always `uv add xxx` never `pip install xxx`
- Favor clear, concise docstring comments. Be sparing with comments outside docstrings.
- Favor short modules, short methods and functions. Name things clearly.
- Never use emojis in code or in print statements or logging.
- keep README.md concise

## Important - debugging and fixing

- When troubleshooting problems, ALWAYS identify root cause BEFORE fixing.
- Reproduce consistently
- PROVE THE PROBLEM FIRST - don't guess.
- Try one test at a time. Be methodical.
- Don't jump to conclusions. Don't apply workarounds

---

## Progress

### Decisions confirmed (2026-04-07)
- Input: real `.twb` / `.twbx` files placed in `input/` folder
- Output: full PBIR folder format (not `.pbix`)
- AI role: translate supported Tableau formulas → DAX
- Live connections, data blending, and complex joins: out of scope for MVP
- Tableau Server API: out of scope for MVP
- Push to Power BI Service: out of scope for MVP
- Anthropic API key, Power BI Desktop, and real Tableau files: all available
- Storage mode for MVP: Import only
- MVP success criteria: generated PBIR opens successfully in Power BI Desktop

### Decisions confirmed (2026-04-20) — T12 DirectQuery design
- Live connections (SQL datasource without extract): **support via DirectQuery mode**, not flag-and-skip
- DirectQuery storage mode: set `mode: directQuery` on affected tables + model-level `defaultMode` in TMDL — low complexity, mechanical change
- Power Query M for DirectQuery: our current simple M expressions fold cleanly to SQL; no change needed for basic table sources; `Value.NativeQuery()` used for custom SQL on SQL-capable sources
- DAX compatibility for DirectQuery: **two-stage approach**
  - Stage 1 (deterministic blocklist): after Claude translates, scan resulting DAX for DirectQuery-incompatible functions (`MEDIAN`, `PERCENTILE`, `PATH`, `DATATABLE`, time intelligence on non-date tables); flag as `status: unsupported_directquery` and exclude from TMDL
  - Stage 2 (prompt-level constraint): when datasource is DirectQuery, tell Claude in the translation prompt to restrict output to DirectQuery-compatible DAX only; Claude self-restricts first, blocklist catches anything that slips through
  - Rationale: relying solely on Claude risks hallucination; relying solely on blocklist misses subtle invalid patterns; both together give defense in depth
- Relationships in DirectQuery: same-source constraint enforced (cross-source relationships not supported); our current workbooks are already single-source so no change needed
- Credentials/connection: user responsibility after opening in PBI Desktop; migration report notes this explicitly
- Data blending: still flagged as unsupported (sheets referencing >1 datasource)

### Status (2026-04-20)
- Planning: complete
- T1: complete — uv project initialised, folder structure created, stubs for all modules, CLI smoke-tested end to end
- T2: complete — `input/simple.twb` added (Tableau Superstore sample, Excel connection, single Orders table, one sheet "Sheet 1", no calculated fields, no joins)
- T3: complete — `parser.py` implemented; parses datasource (connection type, filename, table, 21 columns), worksheet (name, datasource ref, rows/cols shelf fields, mark type), calculated fields, joins, and unsupported pattern detection; `.twbx` unzip supported; validated against `simple.twb`
- T4: complete — `generator.py` generates PBIR SemanticModel (`model.bim` + `definition.pbism`); `transformer.py` maps datasources to TMSL tables with Power Query M expressions
- T5: complete — `generator.py` fixed to write proper PBIR format: `definition/` subfolder with `version.json`, `report.json`, `pages/`; all files include `$schema` and correct required fields per MS spec; `transformer.py` maps sheets to visual descriptors
- T6: complete — PBIR opens successfully in Power BI Desktop 2.152 with data loaded and visual rendered
- T7: complete — multi-table PostgreSQL datasource parsed; connection details (server, dbname, port), tables (schema + name), column→table mapping, and logical-layer relationships all extracted; `postgres` added to supported connection types
- T8: complete — Tableau `object-graph` relationships parsed; transformer produces one PBI table per physical table with correct field-to-table binding; relationships written to `model.tmdl`; end-to-end validated against `input/simple_join.twb`; 30 tests passing
- T9: complete — calculated fields extracted with `name`, `internal_name`, `formula`, `datatype`, `role`; `calc_name_map` built per datasource; shelf refs to `Calculation_xxx` resolved and skipped from visual projections; recorded in `migration_report.json` as `pending_translation`; 13 dedicated unit tests added (`tests/test_t9_calculated_fields.py`); 43 tests passing; all 3 input workbooks validated end-to-end
- T10: complete — worksheet filters extracted from all sheets; `_parse_filters(ws)` added to `parser.py`; parses `categorical` and `quantitative` filter classes; extracts field name from `[ds_ref].[prefix:name:suffix]` column attribute; includes `min`/`max` for quantitative (date/range) filters; skips Tableau virtual fields; `filters` key added to each sheet dict; transformer passes filters to visual descriptors and records `sheet_filters` in migration report; 10 dedicated unit tests added (`tests/test_t10_filters.py`); validated against all 3 workbooks (Superstore has categorical + quantitative filters; simple has none); 65 tests passing total
- T11: complete — `.twbx` support end-to-end; `extract_twbx_data(path, dest_dir)` added to `parser.py`; extracts all non-`.twb` embedded files into a flat directory; `main.py` auto-detects `.twbx` input, extracts data to `output/<stem>_data/`, passes it as `data_dir` to generator; validated against `input/tabpbi.twbx` (3 datasources, 12 sheets, 0 pipeline errors); 7 dedicated tests in `tests/test_t11_twbx.py`; 72 tests passing total
- T13: complete — new `translator.py` calls Claude (`claude-opus-4-7`) per calc field to translate Tableau formula → DAX; `translate_calc_fields_in_transformed()` called from `main.py` after `transform()`; translated measures written to TMDL alongside shelf-derived measures; migration report records `status: translated` + `dax` for each translated field, `status: unsupported` for unsupported ones; validated against `input/Superstore.twb` (21 calc fields: 10 translated, 11 unsupported); 0 errors end-to-end; parser fix: Tableau virtual fields (`:Measure Names`, `:Measure Values`) now skipped from shelf parsing
- T13 improvement (2026-04-20) — LOD expressions now translated: added `{FIXED}→CALCULATE+ALLEXCEPT`, `{INCLUDE}→CALCULATE+VALUES`, `{EXCLUDE}→CALCULATE+ALL` rules to prompt; `translate_formula()` now accepts optional `columns` list for column-level context; `translate_calc_fields_in_transformed()` passes per-table column names to Claude; `Order Profitable?` (`{fixed [Order ID]: SUM([Profit])} > 0`) now correctly translates; `Total Compensation` correctly reclassified as unsupported (depends on Parameter-based fields); mock in `test_e2e.py` updated to match new signature; 72 tests passing
- E2E tests: complete — `tests/test_e2e.py` added with 15 tests covering T9 and T13 end-to-end using real `.twb` files and mocked Claude translation (no API calls); verifies pending fields stay out of TMDL, translated measures land in TMDL, unsupported stay out, validator passes 0 errors for all 3 workbooks (simple, simple_join, Superstore)
- T12: complete — physical-layer joins (INNER/LEFT/RIGHT/FULL OUTER), custom SQL, live connections (DirectQuery mode), data blending detection; 25 dedicated unit tests in `tests/test_t12.py`; parametrised E2E test across all 5 input files (`simple.twb`, `simple_join.twb`, `simple_join_calculated_line.twb`, `Superstore.twb`, `tabpbi.twbx`) — all pass 0 errors
- Tableau XML Schema Conformance (2026-04-20) — reviewed `parser.py` against official XSD 2026.1.0; 6 fixes: full-outer join `"full"` value, unsupported relation types flagged (`union`/`subquery`/`stored-proc`/`pivot`), `parent-name` metadata fallback for source_table, `mark_orientation` attribute parsed, extract `enabled="false"` treated as live, `_AGG_MAP` extended with `var`/`varp`/`stdev`/`stdevp`; 6 new tests added
- T14: complete — Tableau → PBI visual type mapping expanded and wired; `MARK_TO_VISUAL` covers high (`Area`→`areaChart`, `Pie`→`pieChart`) and medium (`Circle`/`Shape`→`scatterChart`, `Polygon`/`Multipolygon`→`filledMap`, `PolyLine`→`map`) confidence mappings; `_VISUAL_ROLES` extended with correct PBI role names per visual type; `mark_orientation="y"` on explicit `Bar` mark flips to `Column` (columnChart); unsupported mark types (`Heatmap`, `GanttBar`, `VizExtension`, etc.) fall back to `tableEx` and emit warning in `report["unsupported"]`; `_SUPPORTED_MARK_TYPES` constant added; 14 dedicated unit tests in `tests/test_t14.py`; **120 tests passing total; all 5 input workbooks pass E2E with 0 errors**
- T15–T19: complete (built incrementally) — semantic model files, report files, migration_report.json, CLI, and automated validator all operational
- T19 PBI Desktop verification (2026-04-21) — all 5 workbooks generate with 0 pipeline errors; `simple.Report` confirmed opens and renders correctly in PBI Desktop; `simple_join.Report` confirmed opens and both visuals render correctly (category/DeltaOrder column chart + category/Margin bar chart); `simple_join_calculated_line.Report` confirmed opens and renders correctly (2 sheets: column chart + line chart); `Superstore.Report` pending manual PBI Desktop verification (requires `Sales Commission.csv` in `data/`); `tabpbi.Report` pending manual PBI Desktop verification
- Bug fix (2026-04-21): multi-table column disambiguation — Tableau uses logical name `order_id (returns)` for `returns.order_id` to avoid name collision; PBI/TMDL tables are separate so physical name is correct; fixed `parser.py` to capture `remote_name` (physical column) from `cols/map`; fixed `transformer.py` to use physical name as TMDL column name and `sourceColumn`; resolves "ToColumn refers to an object which cannot be found" error on open
- Bug fix (2026-04-21): translated calc fields missing from visual projections — transformer was skipping ALL calc fields from shelf projections (pending translation); fixed to include calc fields as tentative measure projections using display name; after translation, `translate_calc_fields_in_transformed()` prunes projections for unsupported fields; `DeltaOrder` and `Margin` now correctly appear on Y-axis
- Bug fix (2026-04-21): cross-table formula translation — Claude was returning UNSUPPORTED for `DeltaOrder` (`COUNTD([order_id]) - COUNTD([order_id (returns)])`) because it only received the primary table's columns; fixed `translate_formula()` to accept `all_tables` dict and include related table columns + disambiguation note in prompt; `DeltaOrder` now correctly translates to `DISTINCTCOUNT('orders'[order_id]) - DISTINCTCOUNT('returns'[order_id])`; 117 tests passing
- Bug fix (2026-04-21): Tableau date derivation prefix (`yr:order_date`) — shelf fields with date-part prefixes (`yr`, `qr`, `mn`, `wk`, `hr`) now parsed with `date_part` key via `_DATE_PART_MAP` in `parser.py`; transformer binds the raw date column to the visual axis (PBI's native date hierarchy handles year/month/day granularity); TMDL calculated columns rejected by PBI Desktop 2.152 TMDL parser (`expression` property not supported on `column` objects in this version)
- Bug fix (2026-04-21): duplicate relationships — relationships were written in both `model.tmdl` (inline) and a stale `relationships.tmdl` left by PBI Desktop save; fixed generator to write relationships exclusively to `relationships.tmdl` (standalone top-level objects, matching PBI Desktop's own save format); `model.tmdl` no longer contains relationship blocks; stale `relationships.tmdl` cleaned up on each pipeline run
- Bug fix (2026-04-21): `compatibilityLevel: 1550` downgrade rejected — PBI Desktop 2.152 operates at compatibility level 1600; regenerating with 1550 caused "CompatibilityLevel downgrade" error after any prior PBI Desktop open/save; fixed generator to write `compatibilityLevel: 1600` in `database.tmdl`
- Multi-database connector support (2026-04-21) — Power Query M generation extended to all major SQL databases; `_SQL_CONNECTOR` dict in `generator.py` maps `sqlserver`→`Sql.Database`, `mysql`→`MySQL.Database`, `redshift`→`AmazonRedshift.Database`, `snowflake`→`Snowflake.Databases`, `oracle`→`Oracle.Database`, `bigquery`→`GoogleBigQuery.Database`; custom SQL via `Value.NativeQuery()` works for all; `_SUPPORTED_CONN_TYPES` in `parser.py` updated to include all 6 new types so they no longer emit "unsupported connection type" warnings; 124 tests passing
- Bug fix (2026-04-21): CSV (`textscan`) datasource generated hard `error` in M expression — `generator.py:_build_m_expression()` had no handler for `textscan`; added `Csv.Document(File.Contents(...))` branch; path resolved directly from `conn["filename"]` (already has `.csv` extension, no stem lookup needed); 117 unit tests passing after fix
- Bug fix (2026-04-21): translated measures referencing internal Tableau calc IDs — Claude received raw Tableau formula containing `[Calculation_xxx]` tokens and passed them through verbatim as DAX measure references (syntactically valid DAX, so no UNSUPPORTED returned), but PBI Desktop cannot resolve them; fixed by adding `_substitute_calc_names()` in `translator.py` that replaces every `[Calculation_xxx]` with its display name before the formula is sent to Claude; `transformer.py` now merges all datasource `calc_name_map` dicts into a single `calc_name_map` on the transformed output so the translator can access it; `Ship Status` now correctly translates to `IF([Days to Ship Actual] > [Days to Ship Scheduled], ...)` instead of referencing internal IDs; 117 tests passing
- Superstore.Report regenerated (2026-04-21) — 0 pipeline errors; `compatibilityLevel: 1600`, no `expression=` on columns, `Ship Status` uses real measure names; pending manual PBI Desktop verification (requires `Sales Commission.csv` placed in `data/` folder)
- Bug fix (2026-04-21): compound multi-measure cols shelf not parsed — Tableau encodes multiple measures on the Columns shelf as `(field1 + field2)` (parenthesised, ` + `-separated); parser only extracted the first field; fixed `_parse_shelf_fields()` in `parser.py` to strip outer parens and split on ` + ` before applying existing per-token logic; both `CNTD(Product ID)` and `SUM(Sales)` now parsed correctly; `simple.twb` updated to this workbook (Excel, Category on rows, two measures on cols, categorical filter)
- Bug fix (2026-04-21): multi-measure cols → separate PBI visuals per measure — Tableau's two-panel side-by-side layout (one panel per measure) has no direct PBI equivalent; fixed `transformer.py` `_process_sheets()` to detect when `col_fields` contains >1 measure and emit one visual per measure, each sharing the same `page_name` (sheet name) and dimension row fields; `generator.py` `_write_pages()` now groups visuals by `page_name` and lays multiple visuals side-by-side (x=20, x=640) within one page section; `_write_visual()` accepts `x_offset` param; visual folder naming uses a global index (`visual_1`, `visual_2`, …) preserving backward compatibility for single-measure sheets; 120 tests passing
- Bug fix (2026-04-21): Power Query column type inference — `Excel.Workbook(..., null, true)` with `delayTypes=true` + no explicit cast caused PBI Desktop to load numeric columns (e.g. `Sales`) as String, making `SUM` measures fail with "SUM cannot work with values of type String"; root cause: Tableau's column `datatype` metadata is the authoritative source; fixed `_build_m_expression()` in `generator.py` to accept column list and append `Table.TransformColumnTypes` step for Excel and CSV sources; `_M_TYPE_MAP` maps PBI dataTypes to M type literals (`double→Decimal.Type`, `int64→Int64.Type`, `string→type text`, `dateTime→type datetime`, `boolean→type logical`); types are now explicit, sourced from Tableau metadata, not inferred at runtime; 120 tests passing

### Validator (complete — plan at docs/superpowers/plans/2026-04-16-pbir-validator.md)
- Design: approved — Option C: jsonschema against official MS schemas + semantic cross-reference checks
- V1: complete — `jsonschema` 4.26.0 added, `.pbir_schema_cache/` added to `.gitignore`
- V2: complete — `ValidationResult` dataclass + `load_schema()` with local cache; `tests/test_validator.py` created, 3 tests pass
- V3: complete — Phase 1: file presence checks (`check_presence`); 9 tests pass
- V4: complete — Phase 2: JSON schema validation (`check_schemas`, `_validate_file`); 17 tests pass
- V5: complete — Phase 3: semantic cross-reference checks (`check_semantics`, `_extract_projections`); 25 tests pass
- V6: complete — top-level `validate()` orchestrator + `print_results()`; 27 tests pass
- V7: complete — standalone CLI entry point; verified against `output/simple.Report`, exits 0 with 1 expected warning
- V8: complete — `validate()` integrated into `main.py` pipeline; exits 1 on errors; 27 tests pass
- V9: complete — updated for PBI Desktop 2.152 format: `pages.json` presence check added; `definition.pbir` removed from schema validation (no `$schema` in new format); schema versions updated

### UI Test Layer (complete — 2026-04-19)
- Tool: `pywinauto` + `Pillow` (Windows UI Automation, no external driver/service needed)
- PBI Desktop: Store app at `C:\Program Files\WindowsApps\Microsoft.MicrosoftPowerBIDesktop_2.152.1279.0_x64__8wekyb3d8bbwe\bin\PBIDesktop.exe`
- Test file: `tests/test_pbi_desktop.py` — 3 tests, all passing
- L1 (open without errors): complete — launches PBI Desktop, waits for main window, asserts no error dialog, saves screenshot to `output/test_screenshots/`
- L3 (visual type correct): complete — asserts `visualType` in each generated `visual.json` matches expected type from `transformed.json`; saves screenshot for human review
- Key finding: PBI Desktop renders visuals inside a WebView (Chromium), so visual types are NOT exposed in the native UIA accessibility tree. Visual type validation is done against the generated PBIR files instead, which is the authoritative pipeline output.

### Visual & Aggregation Mapping (complete — 2026-04-19)
- Debug JSON dumps added to pipeline: `output/<stem>.parsed.json` and `output/<stem>.transformed.json` written on every run for inspection
- Visual type inference: `parser.py` now preserves Tableau shelf field prefix as `{name, continuous, aggregation}` dict; `transformer.py` infers PBI visual type from shelf layout when Tableau mark is `Automatic`
- Aggregation extraction: Tableau prefix codes (`ctd`, `sum`, `avg`, `cnt`, etc.) decoded to DAX functions; aggregated shelf fields auto-generate named DAX measures (e.g. `DISTINCTCOUNT('Table'[Product ID])`) written to TMDL
- Role-based field binding: `generator.py` assigns fields to correct PBI `queryState` roles (`Category`/`Y` for bar/column/line; `Values` for table); uses `Measure` projection type for aggregated fields and `Column` for dimensions
- Tableau → PBI visual type map: `Bar`→`barChart`, `Column`→`columnChart`, `Line`→`lineChart`, `Area`→`areaChart`, `Pie`→`pieChart`, `Circle`/`Shape`→`scatterChart`, `Polygon`/`Multipolygon`→`filledMap`, `PolyLine`→`map`, `Text`/`Automatic`→`tableEx`
- Tableau aggregation → DAX map: `ctd`/`cntd`→`DISTINCTCOUNT`, `cnt`→`COUNTA`, `sum`→`SUM`, `avg`→`AVERAGE`, `min`→`MIN`, `max`→`MAX`, `median`→`MEDIAN`

### Input workbooks (as of 2026-04-21)
- `input/simple.twb` — Excel, 1 table (Orders), Category on Rows, CNTD(Product ID)+SUM(Sales) on Cols (compound shelf), categorical filter on Category; updated 2026-04-21 to test multi-measure and type-cast fixes
- `input/simple_1.twb` — identical to `simple.twb` (same workbook, kept as separate file for investigation)
- `input/simple_join.twb` — PostgreSQL, 2 tables (orders + returns), 1 relationship, 2 calc fields (DeltaOrder, Margin)
- `input/simple_join_calculated_line.twb` — PostgreSQL, 3 tables (people + orders + returns), no calc fields; confirms multi-table path generalises beyond 2 tables
- `input/Superstore.twb` — Excel, 3 datasources (Sales Target, Sample - Superstore, Sales Commission), 21 calc fields; primary T13 validation workbook

### T7 + T8: Multi-table datasources & relationships (complete — 2026-04-19)
- Input: `input/simple_join.twb` — PostgreSQL connection (AWS RDS), two tables (`superstore.orders`, `superstore.returns`), Tableau logical-layer relationship on `order_id`
- **Parser**: extracts PostgreSQL connection details (server, dbname, port); parses multiple tables from `collection`-type relation; column→source_table mapping from `<cols><map>` + `<metadata-records>`; relationship extracted from `<object-graph>`; `postgres` added to supported connection types
- **Transformer**: multi-table datasources produce one PBI table per physical table; field→table lookup for correct per-field `SourceRef.Entity` in visuals; DAX measures scoped to their source table; relationships passed through to output
- **Generator**: PostgreSQL Power Query M expression added (`PostgreSQL.Database(...)`); relationships written to `model.tmdl` as `relationship '...' fromColumn/toColumn`; per-field entity references in visual.json use correct table
- **Validator**: `_find_model_dir` fixed to match SemanticModel by stem (not first glob) — critical for multi-output directories
- **Tests**: 30 passing (up from 27); test fixtures updated to include `pages.json`; stale assertions corrected

---

## Architecture

### Folder Structure

```
TabToPowerBI/
├── CLAUDE.md
├── README.md
├── pyproject.toml          ← uv managed
├── .env                    ← ANTHROPIC_API_KEY
│
├── input/                  ← drop .twb / .twbx files here
├── output/                 ← generated PBIR folders land here
│
└── tab_to_pbi/
    ├── __init__.py
    ├── main.py             ← CLI, wires modules, writes migration_report.json
    ├── parser.py           ← parse .twb XML + unzip .twbx
    ├── transformer.py      ← deterministic mapping + Claude formula translation
    └── generator.py        ← write PBIR folder/file structure
```

### Module Responsibilities

| Module | Does one thing |
|--------|---------------|
| `parser.py` | Reads `.twb`/`.twbx`, returns a plain dict: data sources, joins, fields, sheets, unsupported patterns |
| `transformer.py` | Applies deterministic mappings first, uses Claude only for supported Tableau formula → DAX translation |
| `generator.py` | Takes transformed dict, writes valid PBIR folder to `output/` |
| `main.py` | Wires modules, accepts CLI arg, writes `migration_report.json` |

### Data Flow

```
input/foo.twb
    → parser.py      → workbook dict (data sources, joins, fields, sheets)
    → transformer.py → transformed dict (DAX measures, PBI visuals, relationships)
    → generator.py   → output/foo.Report/ + output/foo.SemanticModel/
    → reporting.py   → output/foo.migration_report.json
```

### PBIR Output Structure

```
output/MyReport.Report/
├── definition.pbir                  ← no $schema field (PBI Desktop 2.152+)
└── definition/
    ├── version.json                 ← version: "2.0.0"
    ├── report.json                  ← schema 3.2.0
    └── pages/
        ├── pages.json               ← REQUIRED: pageOrder + activePageName manifest
        └── ReportSection1/
            ├── page.json            ← schema 2.1.0
            └── visuals/
                └── visual_1/
                    └── visual.json

output/MyReport.SemanticModel/
├── definition.pbism
└── definition/
    ├── database.tmdl
    ├── model.tmdl
    └── tables/
        └── <TableName>.tmdl
```

### PBI Desktop 2.152 Compatibility Notes

These were discovered through T6 verification against PBI Desktop 2.152 (March 2026):

- **`pages.json` is required** — `definition/pages/pages.json` must exist with `pageOrder` and `activePageName`. Without it, PBI Desktop creates no explorations and throws a JS rendering crash (`Cannot read properties of undefined (reading 'visualContainers')`).
- **Schema versions have advanced** — `report/3.2.0`, `page/2.1.0` (not 1.0.0). Microsoft does not publish these schemas publicly, so the validator warns rather than validates them.
- **`definition.pbir` has no `$schema` field** in the new format.
- **`version.json` version is `"2.0.0"`**, not `"1.0.0"`.
- **`report.json` format changed**: `reportVersionAtImport` is now an object `{"visual":..., "report":..., "page":...}`; `layoutOptimization` removed; `settings` block added.
- **TMDL format** (`PBI_tmdlInDataset` preview feature) must be enabled in PBI Desktop for TMDL semantic models to load. TMSL (`model.bim`) is the fallback for older versions.
- **Do not save in PBI Desktop** during testing — it will overwrite the generated files. If accidentally saved, delete `output/` and regenerate.
- **Data file must be `.xlsx`** — PBI Desktop 64-bit cannot read `.xls` without the ACE OLEDB 12.0 driver. Generator prefers `.xlsx` over `.xls` when both exist.
- **`compatibilityLevel` must be `1600`** — PBI Desktop 2.152 runs at level 1600; writing 1550 causes a "CompatibilityLevel downgrade" error after first open.
- **`calculatedColumn` TMDL keyword not supported** — PBI Desktop 2.152 rejects both `calculatedColumn` keyword and `expression` property on `column` objects. Calculated columns cannot be written in TMDL in this version; use measures or raw columns instead.
- **Relationships must be in `relationships.tmdl`** — writing relationships inline in `model.tmdl` AND having a `relationships.tmdl` (from a prior PBI Desktop save) causes a "TMDL objects cannot be merged" error. Generator writes relationships exclusively to `relationships.tmdl`.

---

## MVP Task List

**Phase 1 — Setup**
- T1: ✓ `uv init`, project structure, input/output folders, `.env` for Anthropic key
- T2: Add real Tableau workbooks to `input/` for development and validation

**Phase 2 — Vertical Slice**
- T3: ✓ Parse one simple `.twb` — one datasource, one sheet, one supported visual
- T4: ✓ Generate the smallest valid PBIR semantic model
- T5: ✓ Generate one report page and one visual
- T6: ✓ Verify the PBIR output opens in Power BI Desktop

**Phase 3 — Expand Parsing**
- T7: ✓ Extract data sources (connection type, server, database, table info) — PostgreSQL multi-table supported
- T8: ✓ Extract simple joins / relationships (Tableau logical-layer `object-graph` relationships with explicit key columns)
- T9: ✓ Extract calculated fields — name, internal Tableau name, formula, datatype, role; shelf refs to `Calculation_xxx` resolved via `calc_name_map`; pending fields skipped from visual projections; recorded in `migration_report.json` as `status: pending_translation`; 13 unit tests; all 3 input workbooks pass end-to-end
- T10: ✓ Extract sheets (name, viz type, filters, dimensions, measures used)
- T11: ✓ Handle `.twbx` (unzip → `.twb` + embedded data files)
- T12: complete — Detect and log unsupported patterns + expand join support + DirectQuery mode; scope:
  - Physical-layer joins (`<relation type="join">`): INNER + LEFT + RIGHT OUTER supported → mapped to PBI model relationships (RIGHT = flipped LEFT); FULL OUTER + non-equi → flagged as unsupported
  - Custom SQL (`<relation type="text">`): wrap in `Value.NativeQuery()` for SQL-capable sources (postgres); flag as unsupported for Excel/CSV
  - Live connections: detect SQL-type datasources without extract → generate DirectQuery mode PBIR (set `mode: directQuery` on tables + model); two-stage DAX safety (prompt constraint + blocklist); credentials note in migration report
  - Data blending: detect sheets referencing >1 datasource → flag as unsupported
  - 25 dedicated unit tests in `tests/test_t12.py`; 97 tests passing total (up from 72)

**Phase 4 — AI Transform**
- T13: ✓ Translate supported calculated fields → DAX using Claude (`claude-opus-4-7`); `translator.py` module; called from `main.py` after `transform()`; translated measures written to TMDL; Superstore.twb: 10/21 translated, 11 unsupported (LOD, Parameters, cross-datasource, table calcs); 0 errors end-to-end
- T14: Map supported Tableau viz types → Power BI visual type + config using deterministic rules

**Phase 5 — Generate PBIR**
- T15: Generate semantic model files (`model.bim`, `definition.pbism`)
- T16: Generate report files (`report.json`, `definition.pbir`, pages, visuals) and write full PBIR folder
- T17: Write `migration_report.json` (transformed items, warnings, unsupported items)

**Phase 6 — CLI + Validate**
- T18: CLI: `uv run tab_to_pbi/main.py input/MyReport.twb`
- T19: Validate end to end on 2-3 real supported workbooks

### MVP Scope

| In scope | Out of scope |
|----------|-------------|
| .twb and .twbx files | Tableau Server API |
| PBIR folder output | Push to Power BI Service |
| Import mode (extract-based) + DirectQuery (live SQL connections) | DirectQuery on non-SQL sources |
| Single primary datasource | Data blending |
| Simple inner/left joins with explicit keys | Complex joins / federated joins |
| Table, bar, line visuals | Complex custom visuals |
| Supported calculated fields → DAX | Full Tableau formula coverage |
| Migration report listing transformed and unsupported items | Row-level security |

## Validation Requirements

- Validate every increment against real Tableau workbooks.
- Treat unsupported features as explicit findings, not silent fallbacks.
- Keep generated PBIR output minimal and valid before expanding feature coverage.
- MVP is not complete until the generated PBIR opens successfully in Power BI Desktop without manual repair.

## Implementation Principles

- Prefer deterministic mappings over AI whenever possible.
- Use AI only where it adds clear value: supported Tableau formula → DAX translation.
- Keep parsing separate from transformation and PBIR generation.
- Preserve traceability for AI decisions by storing prompt inputs and outputs when needed for debugging.
- Fail clearly when the workbook contains unsupported constructs.

## Acceptance Criteria

- A supported `.twb` migrates end to end through the CLI.
- The generated PBIR opens in Power BI Desktop without manual repair.
- At least one translated calculated field is referenced correctly in the semantic model or report.
- At least one report page with one supported visual renders correctly.
- Unsupported workbook features are detected and written to the migration report.
- The output includes a machine-readable `migration_report.json`.

---

## Features

| Feature | Description | Status |
|---------|-------------|--------|
| Excel / CSV datasource | Parses `.twb`/`.twbx` with Excel and CSV connections; generates Power Query M with explicit column types | Complete |
| PostgreSQL multi-table datasource | Parses multi-table federated postgres connections; maps each physical table to a PBI table with correct column binding | Complete |
| SQL datasources (SQLServer, MySQL, Redshift, Snowflake, Oracle, BigQuery) | Generates correct Power Query M connector per SQL dialect; custom SQL wrapped in `Value.NativeQuery` | Complete |
| Relationships | Extracts Tableau logical-layer (object-graph) and physical-layer (JOIN) relationships; writes `relationships.tmdl` | Complete |
| Calculated fields → DAX | Translates supported Tableau formulas to DAX via Claude (`claude-opus-4-7`); LOD expressions, cross-table refs supported | Complete |
| Visual type mapping | Maps Tableau mark types to PBI visual types (bar, column, line, area, pie, scatter, map, table) | Complete |
| Aggregation → DAX measures | Decodes Tableau shelf aggregation prefixes (SUM, COUNTD, AVG, etc.) into named DAX measures written to TMDL | Complete |
| DirectQuery mode | Live SQL connections (no extract) generated as DirectQuery with two-stage DAX safety check | Complete |
| `.twbx` support | Extracts embedded data files from `.twbx` archives; resolves file paths for M expressions | Complete |
| Filter migration | Migrates Tableau worksheet filters (visual-level) and shared-view filters (report-level) to PBI `filterConfig` JSON; supports categorical (In) and quantitative (Between/Comparison) filter types; date, datetime, integer, decimal literal formatting | Complete |
| Migration report | Writes `migration_report.json` with translated fields, unsupported items, sheet filters, and table inventory | Complete |
| PBIR validator | JSON-schema validation + semantic cross-reference checks; integrated into pipeline; exits 1 on errors | Complete |
| Data labels | Migrates Tableau `mark-labels-show` setting to PBI `objects.labels` in `visual.json`; supported for all chart visual types (bar, column, line, area, pie, scatter, map); skipped for table (`tableEx`) visuals | Complete |
| Visual sorting | Migrates Tableau worksheet sorts (`computed-sort`, `natural-sort`, `alphabetic-sort`) to PBI `sortDefinition` in `visual.json`; computed-sort (by measure) uses `Measure` field expression; natural/alphabetic use `Column`; multi-sort arrays supported; manual sort logged as unsupported; computed-sorts referencing untranslated calc fields pruned with warning; applies to all visual types including table | Complete |
