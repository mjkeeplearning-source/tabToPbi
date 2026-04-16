# PBIR Validator Design

**Date:** 2026-04-16
**Status:** Approved

## Overview

Add an offline PBIR validator that catches structural and schema errors in generated output before Power BI Desktop is involved. It runs automatically at the end of the pipeline and is also available as a standalone CLI command.

## Approach

Option C: `jsonschema`-based validation against the official Microsoft JSON schemas, supplemented by semantic cross-reference checks. Schemas are fetched once from Microsoft's public URLs and cached locally. All subsequent runs are fully offline.

## Architecture

Single new module: `tab_to_pbi/validator.py`

Public entry point:
```python
def validate(report_dir: Path) -> list[ValidationResult]
```

Three phases run in sequence:

### Phase 1 — File Presence
Check required files and folders exist before any JSON parsing. Fail fast with clear path errors.

### Phase 2 — JSON Schema Validation
For each required JSON file:
1. Parse JSON
2. Extract `$schema` field
3. Load schema from local cache (fetch from Microsoft if absent)
4. Run `jsonschema.validate(data, schema)`
5. Collect errors as `ValidationResult(level="ERROR", file=..., message=...)`

Phase 3 only runs if Phase 2 has no errors.

### Phase 3 — Semantic Cross-Reference Checks
Cross-file consistency checks that JSON schema cannot cover:
- `definition.pbir` → `byPath.path` resolves to an existing SemanticModel folder on disk
- Each `visual.json` → every `SourceRef.Entity` matches a table name in `model.bim`
- Each `visual.json` → every column `Property` exists in that table's columns in `model.bim`
- `model.bim` → at least one table exists
- Each table in `model.bim` → at least one partition exists

## Data Structures

```python
@dataclass
class ValidationResult:
    level: str    # "ERROR" or "WARNING"
    file: str     # relative path from report_dir parent
    message: str
```

**Severity rules:**
- `ERROR` — blocking (missing required file, invalid JSON, schema violation, broken cross-reference)
- `WARNING` — non-blocking (no relationships in model.bim, visual has no projections, unsupported M connection type)

## Complete Check Inventory

| Phase | Check | Level |
|-------|-------|-------|
| Presence | `definition.pbir` exists | ERROR |
| Presence | `definition/` folder exists | ERROR |
| Presence | `definition/version.json` exists | ERROR |
| Presence | `definition/report.json` exists | ERROR |
| Presence | `definition/pages/` exists with at least one page folder | ERROR |
| Presence | Each page folder contains `page.json` | ERROR |
| Presence | `SemanticModel/definition.pbism` exists | ERROR |
| Presence | `SemanticModel/model.bim` exists | ERROR |
| Schema | `definition.pbir` valid against MS schema | ERROR |
| Schema | `definition/version.json` valid against MS schema | ERROR |
| Schema | `definition/report.json` valid against MS schema | ERROR |
| Schema | Each `page.json` valid against MS schema | ERROR |
| Schema | Each `visual.json` valid against MS schema | ERROR |
| Semantic | `byPath.path` resolves to existing SemanticModel folder | ERROR |
| Semantic | Each visual `SourceRef.Entity` exists as table in `model.bim` | ERROR |
| Semantic | Each visual column `Property` exists in that table's columns | ERROR |
| Semantic | `model.bim` has at least one table | ERROR |
| Semantic | Each table has at least one partition | ERROR |
| Semantic | No relationships in `model.bim` (Import mode, expected) | WARNING |
| Semantic | Visual has no field projections | WARNING |
| Semantic | M expression contains unsupported connection type | WARNING |

## Schema Cache

- Location: `.pbir_schema_cache/` at project root
- Added to `.gitignore`
- One JSON file per schema URL, filename = slugified URL path
- Fetched using stdlib `urllib.request` (no extra network dependency)
- Cache entries are versioned by URL — never go stale unless schema version changes

Example cache filenames:
```
.pbir_schema_cache/
  fabric-item-report-definitionProperties-2.0.0-schema.json
  fabric-item-report-definition-versionMetadata-1.0.0-schema.json
  fabric-item-report-definition-report-1.0.0-schema.json
  fabric-item-report-definition-page-1.0.0-schema.json
  fabric-item-report-definition-visualContainer-1.0.0-schema.json
```

## Output Format

```
Validating output/simple.Report...

  ERROR   simple.Report/definition/pages/ReportSection1/page.json
          'displayOption' is a required property

  WARNING simple.SemanticModel/model.bim
          No relationships defined (expected for Import mode)

2 errors, 1 warning
Validation failed.
```

Clean output:
```
Validating output/simple.Report...
All checks passed (0 errors, 0 warnings).
```

## Integration Points

**Standalone CLI:**
```
uv run tab_to_pbi/validator.py output/simple.Report
```
Exit code `0` = no errors, `1` = any errors. Warnings do not affect exit code.

**Pipeline (`main.py`):**
```python
results = validate(report_path)
_print_validation(results)
if any(r.level == "ERROR" for r in results):
    sys.exit(1)
```

## New Dependency

`jsonschema` — added via `uv add jsonschema`.

## Files Changed

| File | Change |
|------|--------|
| `tab_to_pbi/validator.py` | New — validator module and CLI entry point |
| `tab_to_pbi/main.py` | Call `validate()` after `generate()`, exit 1 on errors |
| `.gitignore` | Add `.pbir_schema_cache/` |
| `pyproject.toml` | Add `jsonschema` dependency |
