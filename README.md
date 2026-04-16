# TabToPowerBI

Automates migration of Tableau workbooks (`.twb` / `.twbx`) to Microsoft Power BI PBIR format.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Anthropic API key (for formula translation)
- Power BI Desktop (to open generated output)

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

## What it does

1. **Parse** — reads `.twb`/`.twbx`, extracts datasources, sheets, calculated fields
2. **Transform** — maps to Power BI structures; uses Claude to translate supported Tableau formulas → DAX
3. **Generate** — writes a valid PBIR folder (semantic model + report pages/visuals)
4. **Validate** — checks JSON schemas and cross-references; exits 1 on errors

## Scope

| Supported | Not supported |
|-----------|--------------|
| `.twb` and `.twbx` files | Tableau Server API |
| Import mode | DirectQuery / live connections |
| Single datasource, simple joins | Data blending, complex joins |
| Table, bar, line visuals | Custom visuals |
| Calculated field → DAX translation | Full Tableau formula coverage |
