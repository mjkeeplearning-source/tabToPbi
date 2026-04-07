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

### Status (2026-04-07)
- Planning: complete
- T1: complete — uv project initialised, folder structure created, stubs for all modules, CLI smoke-tested end to end
- T2: complete — `input/simple.twb` added (Tableau Superstore sample, Excel connection, single Orders table, one sheet "Sheet 1", no calculated fields, no joins)
- T3: complete — `parser.py` implemented; parses datasource (connection type, filename, table, 21 columns), worksheet (name, datasource ref, rows/cols shelf fields, mark type), calculated fields, joins, and unsupported pattern detection; `.twbx` unzip supported; validated against `simple.twb`
- T4: not started — next step: generate the smallest valid PBIR semantic model

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
├── definition.pbir
├── report.json
└── pages/
    └── ReportSection<id>/
        ├── page.json
        └── visuals/
            └── <visual-id>/
                └── visual.json

output/MyReport.SemanticModel/
├── model.bim
└── definition.pbism
```

---

## MVP Task List

**Phase 1 — Setup**
- T1: ✓ `uv init`, project structure, input/output folders, `.env` for Anthropic key
- T2: Add real Tableau workbooks to `input/` for development and validation

**Phase 2 — Vertical Slice**
- T3: Parse one simple `.twb` — one datasource, one sheet, one supported visual
- T4: Generate the smallest valid PBIR semantic model
- T5: Generate one report page and one visual
- T6: Verify the PBIR output opens in Power BI Desktop

**Phase 3 — Expand Parsing**
- T7: Extract data sources (connection type, server, database, table info)
- T8: Extract simple joins (inner/left joins with explicit keys only)
- T9: Extract calculated fields (name + Tableau formula)
- T10: Extract sheets (name, viz type, filters, dimensions, measures used)
- T11: Handle `.twbx` (unzip → `.twb` + embedded data files)
- T12: Detect and log unsupported patterns (data blending, custom SQL, live connections, complex joins)

**Phase 4 — AI Transform**
- T13: Translate supported calculated fields → DAX using Claude
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
| Import mode only | DirectQuery / live connections |
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
