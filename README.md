# TabToPowerBI

Automates migration of Tableau workbooks (`.twb` / `.twbx`) to Microsoft Power BI PBIR format.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Anthropic API key (for formula translation)
- Power BI Desktop 2.152+ (to open generated output)

## Setup

```bash
uv sync
cp .env.example .env   # add ANTHROPIC_API_KEY
```

## Usage

```bash
# Migrate a workbook
uv run tab_to_pbi/main.py input/MyReport.twb

# Validate generated output
uv run tab_to_pbi/validator.py output/MyReport.Report
```

Output lands in `output/MyReport.Report/` and `output/MyReport.SemanticModel/`.

## Architecture

```
input/foo.twb (or .twbx)
    │
    ▼
parser.py        — parse XML; extract datasources, tables, columns, joins,
    │               calculated fields, sheets, filters, unsupported patterns;
    │               unzip .twbx and locate embedded data files
    │
    ▼  workbook dict
    │
transformer.py   — deterministic mappings: connection type → Power Query M,
    │               mark type → PBI visual type, aggregation → DAX function,
    │               shelf fields → measure/column projections, relationships;
    │               calls Claude (claude-opus-4-7) to translate supported
    │               Tableau formulas → DAX; DirectQuery safety blocklist applied
    │
    ▼  transformed dict
    │
generator.py     — write PBIR folder structure:
    │               SemanticModel (definition.pbism, database.tmdl, model.tmdl,
    │               tables/*.tmdl with measures + columns + relationships)
    │               Report (definition.pbir, report.json, pages.json,
    │               pages/*/page.json, pages/*/visuals/*/visual.json)
    │
    ▼
validator.py     — file presence checks, JSON schema validation,
    │               semantic cross-reference checks; exits 1 on errors
    │
    ▼
output/
  foo.Report/              ← open in Power BI Desktop
  foo.SemanticModel/
  foo.migration_report.json  ← translated fields, warnings, unsupported items
  foo.parsed.json            ← debug: parser output
  foo.transformed.json       ← debug: transformer output
```

### Module responsibilities

| Module | Responsibility |
|--------|---------------|
| `parser.py` | Read `.twb`/`.twbx` XML → plain dict (datasources, joins, fields, sheets) |
| `transformer.py` | Deterministic PBI mappings + Claude formula → DAX translation |
| `generator.py` | Write valid PBIR folder from transformed dict |
| `validator.py` | Schema + semantic validation of generated output |
| `main.py` | CLI entry point; wires modules; writes migration report |

## Scope

| Supported | Not supported |
|-----------|--------------|
| `.twb` and `.twbx` files | Tableau Server API |
| Import mode (extract-based datasources) | Data blending |
| DirectQuery mode (live SQL connections) | Non-SQL live connections |
| Single datasource, inner/left/right joins | Full outer joins, complex joins |
| Calculated field → DAX via Claude | Full Tableau formula coverage |
| LOD expressions (`FIXED`/`INCLUDE`/`EXCLUDE`) | Parameters, table calculations |
| Bar, column, line, area, pie, scatter, map visuals | Custom / extension visuals |
