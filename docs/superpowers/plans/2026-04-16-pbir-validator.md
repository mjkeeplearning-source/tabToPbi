# PBIR Validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline PBIR validator that checks file presence, JSON schema correctness, and semantic cross-references — callable from the pipeline and as a standalone CLI.

**Architecture:** Three-phase validator (presence → schema → semantic) in a single `validator.py` module. Schemas are fetched from Microsoft's public URLs on first run and cached locally in `.pbir_schema_cache/`. The `jsonschema` library handles schema validation; semantic checks are pure Python dict traversal. `main.py` calls `validate()` after `generate()` and exits non-zero on errors.

**Tech Stack:** Python 3.12, `jsonschema`, `urllib.request` (stdlib), `pytest`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `tab_to_pbi/validator.py` | Create | All validation logic + CLI entry point |
| `tab_to_pbi/main.py` | Modify | Call `validate()` after `generate()`, exit 1 on errors |
| `tests/test_validator.py` | Create | Unit tests for all three phases |
| `.gitignore` | Modify | Add `.pbir_schema_cache/` |
| `pyproject.toml` | Modify | Add `jsonschema` dependency |

---

### Task 1: Add dependency and gitignore entry

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1: Add jsonschema dependency**

```bash
uv add jsonschema
```

Expected output: line added to `pyproject.toml` dependencies.

- [ ] **Step 2: Add cache dir to .gitignore**

Append to `.gitignore`:
```
.pbir_schema_cache/
```

- [ ] **Step 3: Verify import works**

```bash
uv run python -c "import jsonschema; print(jsonschema.__version__)"
```

Expected: prints a version number (e.g. `4.x.x`).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock .gitignore
git commit -m "chore: add jsonschema dependency and cache gitignore"
```

---

### Task 2: ValidationResult dataclass and schema cache

**Files:**
- Create: `tab_to_pbi/validator.py`
- Create: `tests/test_validator.py`

- [ ] **Step 1: Create tests directory and write failing test**

```bash
mkdir tests
touch tests/__init__.py
```

Create `tests/test_validator.py`:

```python
"""Tests for PBIR validator."""
import json
from pathlib import Path
import pytest
from tab_to_pbi.validator import ValidationResult, load_schema


def test_validation_result_fields():
    r = ValidationResult(level="ERROR", file="foo/bar.json", message="missing field")
    assert r.level == "ERROR"
    assert r.file == "foo/bar.json"
    assert r.message == "missing field"


def test_load_schema_returns_dict(tmp_path):
    # Use a real MS schema URL — fetches and caches
    url = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
    cache_dir = tmp_path / ".pbir_schema_cache"
    schema = load_schema(url, cache_dir)
    assert isinstance(schema, dict)
    assert "$schema" in schema or "properties" in schema


def test_load_schema_uses_cache(tmp_path):
    url = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
    cache_dir = tmp_path / ".pbir_schema_cache"
    schema1 = load_schema(url, cache_dir)
    # Second call must not raise and must return same result
    schema2 = load_schema(url, cache_dir)
    assert schema1 == schema2
    # Cache file must exist
    assert any(cache_dir.iterdir())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_validator.py -v
```

Expected: `ImportError` — `validator` module does not exist yet.

- [ ] **Step 3: Create validator.py with ValidationResult and load_schema**

Create `tab_to_pbi/validator.py`:

```python
"""Validate PBIR output folder structure, JSON schemas, and semantic consistency."""

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report"
_DEFAULT_CACHE = Path(".pbir_schema_cache")

SCHEMAS = {
    "definition.pbir": f"{_SCHEMA_BASE}/definitionProperties/2.0.0/schema.json",
    "version.json": f"{_SCHEMA_BASE}/definition/versionMetadata/1.0.0/schema.json",
    "report.json": f"{_SCHEMA_BASE}/definition/report/1.0.0/schema.json",
    "page.json": f"{_SCHEMA_BASE}/definition/page/1.0.0/schema.json",
    "visual.json": f"{_SCHEMA_BASE}/definition/visualContainer/1.0.0/schema.json",
}


@dataclass
class ValidationResult:
    level: str    # "ERROR" or "WARNING"
    file: str     # relative path shown in output
    message: str


def load_schema(url: str, cache_dir: Path = _DEFAULT_CACHE) -> dict:
    """Fetch JSON schema from url, caching locally under cache_dir."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = url.replace("https://", "").replace("/", "-").replace(".", "-")
    cache_file = cache_dir / f"{slug}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    with urllib.request.urlopen(url) as resp:
        data = resp.read().decode()
    cache_file.write_text(data)
    return json.loads(data)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_validator.py -v
```

Expected: all 3 tests PASS (note: `test_load_schema_returns_dict` makes a real HTTP request on first run).

- [ ] **Step 5: Commit**

```bash
git add tab_to_pbi/validator.py tests/test_validator.py tests/__init__.py
git commit -m "feat: ValidationResult dataclass and schema cache loader"
```

---

### Task 3: Phase 1 — file presence checks

**Files:**
- Modify: `tab_to_pbi/validator.py`
- Modify: `tests/test_validator.py`

- [ ] **Step 1: Write failing tests for presence checks**

Add to `tests/test_validator.py`:

```python
from tab_to_pbi.validator import check_presence


def _make_valid_structure(base: Path) -> tuple[Path, Path]:
    """Create minimal valid PBIR folder structure on disk."""
    report_dir = base / "simple.Report"
    model_dir = base / "simple.SemanticModel"
    defn_dir = report_dir / "definition"
    pages_dir = defn_dir / "pages" / "ReportSection1"
    visuals_dir = pages_dir / "visuals" / "visual_1"

    for d in [report_dir, defn_dir, pages_dir, visuals_dir, model_dir]:
        d.mkdir(parents=True)

    (report_dir / "definition.pbir").write_text("{}")
    (defn_dir / "version.json").write_text("{}")
    (defn_dir / "report.json").write_text("{}")
    (pages_dir / "page.json").write_text("{}")
    (visuals_dir / "visual.json").write_text("{}")
    (model_dir / "definition.pbism").write_text("{}")
    (model_dir / "model.bim").write_text("{}")

    return report_dir, model_dir


def test_presence_clean(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    errors = check_presence(report_dir)
    assert errors == []


def test_presence_missing_definition_pbir(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    (report_dir / "definition.pbir").unlink()
    errors = check_presence(report_dir)
    assert any(r.level == "ERROR" and "definition.pbir" in r.message for r in errors)


def test_presence_missing_definition_folder(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    import shutil
    shutil.rmtree(report_dir / "definition")
    errors = check_presence(report_dir)
    assert any(r.level == "ERROR" and "definition/" in r.message for r in errors)


def test_presence_missing_version_json(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    (report_dir / "definition" / "version.json").unlink()
    errors = check_presence(report_dir)
    assert any(r.level == "ERROR" and "version.json" in r.message for r in errors)


def test_presence_missing_report_json(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    (report_dir / "definition" / "report.json").unlink()
    errors = check_presence(report_dir)
    assert any(r.level == "ERROR" and "report.json" in r.message for r in errors)


def test_presence_no_pages(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    import shutil
    shutil.rmtree(report_dir / "definition" / "pages")
    errors = check_presence(report_dir)
    assert any(r.level == "ERROR" and "pages/" in r.message for r in errors)


def test_presence_page_missing_page_json(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    (report_dir / "definition" / "pages" / "ReportSection1" / "page.json").unlink()
    errors = check_presence(report_dir)
    assert any(r.level == "ERROR" and "page.json" in r.message for r in errors)


def test_presence_missing_model_bim(tmp_path):
    report_dir, model_dir = _make_valid_structure(tmp_path)
    (model_dir / "model.bim").unlink()
    errors = check_presence(report_dir)
    assert any(r.level == "ERROR" and "model.bim" in r.message for r in errors)


def test_presence_missing_definition_pbism(tmp_path):
    report_dir, model_dir = _make_valid_structure(tmp_path)
    (model_dir / "definition.pbism").unlink()
    errors = check_presence(report_dir)
    assert any(r.level == "ERROR" and "definition.pbism" in r.message for r in errors)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_validator.py::test_presence_clean -v
```

Expected: `ImportError` — `check_presence` not defined yet.

- [ ] **Step 3: Implement check_presence**

Add to `tab_to_pbi/validator.py` (after `load_schema`):

```python
def check_presence(report_dir: Path) -> list[ValidationResult]:
    """Phase 1: verify all required files and folders exist."""
    results = []

    def err(msg: str) -> None:
        results.append(ValidationResult("ERROR", str(report_dir), msg))

    # Locate sibling SemanticModel dir
    model_dir = _find_model_dir(report_dir)

    # Report required files
    if not (report_dir / "definition.pbir").exists():
        err("Missing required file: definition.pbir")
    defn_dir = report_dir / "definition"
    if not defn_dir.is_dir():
        err("Missing required folder: definition/")
        # Can't check children if folder is absent
        if model_dir and not (model_dir / "model.bim").exists():
            err("Missing required file: model.bim")
        if model_dir and not (model_dir / "definition.pbism").exists():
            err("Missing required file: definition.pbism")
        return results

    if not (defn_dir / "version.json").exists():
        err("Missing required file: definition/version.json")
    if not (defn_dir / "report.json").exists():
        err("Missing required file: definition/report.json")

    pages_dir = defn_dir / "pages"
    if not pages_dir.is_dir() or not any(pages_dir.iterdir()):
        err("Missing required folder with pages: definition/pages/")
    else:
        for page_dir in pages_dir.iterdir():
            if page_dir.is_dir() and not (page_dir / "page.json").exists():
                err(f"Missing required file: {page_dir.relative_to(report_dir.parent)}/page.json")

    # SemanticModel required files
    if model_dir is None:
        err("Missing SemanticModel directory (expected sibling of Report folder)")
    else:
        if not (model_dir / "model.bim").exists():
            err("Missing required file: model.bim")
        if not (model_dir / "definition.pbism").exists():
            err("Missing required file: definition.pbism")

    return results


def _find_model_dir(report_dir: Path) -> Path | None:
    """Find the sibling SemanticModel directory."""
    parent = report_dir.parent
    candidates = list(parent.glob("*.SemanticModel"))
    return candidates[0] if candidates else None
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_validator.py -k "presence" -v
```

Expected: all presence tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tab_to_pbi/validator.py tests/test_validator.py
git commit -m "feat: Phase 1 file presence checks"
```

---

### Task 4: Phase 2 — JSON schema validation

**Files:**
- Modify: `tab_to_pbi/validator.py`
- Modify: `tests/test_validator.py`

- [ ] **Step 1: Write failing tests for schema validation**

Add to `tests/test_validator.py`:

```python
from tab_to_pbi.validator import check_schemas

_VERSION_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
_PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.0.0/schema.json"


def test_schema_valid_version_json(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    (report_dir / "definition" / "version.json").write_text(json.dumps({
        "$schema": _VERSION_SCHEMA,
        "version": "1.0.0",
    }))
    errors = check_schemas(report_dir)
    version_errors = [r for r in errors if "version.json" in r.file]
    assert version_errors == []


def test_schema_invalid_version_json_missing_required(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    # Missing required 'version' field
    (report_dir / "definition" / "version.json").write_text(json.dumps({
        "$schema": _VERSION_SCHEMA,
    }))
    errors = check_schemas(report_dir)
    assert any("version.json" in r.file and r.level == "ERROR" for r in errors)


def test_schema_invalid_json_syntax(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    (report_dir / "definition" / "version.json").write_text("not json {{{")
    errors = check_schemas(report_dir)
    assert any("version.json" in r.file and "Invalid JSON" in r.message for r in errors)


def test_schema_page_missing_display_option(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    (report_dir / "definition" / "pages" / "ReportSection1" / "page.json").write_text(json.dumps({
        "$schema": _PAGE_SCHEMA,
        "name": "ReportSection1",
        "displayName": "Sheet 1",
        # missing displayOption
    }))
    errors = check_schemas(report_dir)
    assert any("page.json" in r.file and r.level == "ERROR" for r in errors)


def test_schema_no_schema_field(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    (report_dir / "definition" / "version.json").write_text(json.dumps({"version": "1.0.0"}))
    errors = check_schemas(report_dir)
    assert any("version.json" in r.file and "missing $schema" in r.message for r in errors)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_validator.py -k "schema" -v
```

Expected: `ImportError` — `check_schemas` not defined yet.

- [ ] **Step 3: Implement check_schemas**

Add to `tab_to_pbi/validator.py`:

```python
import jsonschema


def check_schemas(report_dir: Path, cache_dir: Path = _DEFAULT_CACHE) -> list[ValidationResult]:
    """Phase 2: validate each required JSON file against its declared MS schema."""
    results = []
    model_dir = _find_model_dir(report_dir)
    defn_dir = report_dir / "definition"

    files_to_check = [
        report_dir / "definition.pbir",
        defn_dir / "version.json",
        defn_dir / "report.json",
    ]
    if (defn_dir / "pages").is_dir():
        for page_dir in (defn_dir / "pages").iterdir():
            if page_dir.is_dir():
                files_to_check.append(page_dir / "page.json")
                visuals_dir = page_dir / "visuals"
                if visuals_dir.is_dir():
                    for visual_dir in visuals_dir.iterdir():
                        if visual_dir.is_dir():
                            files_to_check.append(visual_dir / "visual.json")

    for fpath in files_to_check:
        if not fpath.exists():
            continue
        rel = str(fpath.relative_to(report_dir.parent))
        results.extend(_validate_file(fpath, rel, cache_dir))

    return results


def _validate_file(fpath: Path, rel: str, cache_dir: Path) -> list[ValidationResult]:
    """Parse and schema-validate a single JSON file."""
    results = []
    try:
        data = json.loads(fpath.read_text())
    except json.JSONDecodeError as e:
        results.append(ValidationResult("ERROR", rel, f"Invalid JSON: {e.msg} at line {e.lineno}"))
        return results

    schema_url = data.get("$schema")
    if not schema_url:
        results.append(ValidationResult("ERROR", rel, "missing $schema field — cannot validate"))
        return results

    try:
        schema = load_schema(schema_url, cache_dir)
    except Exception as e:
        results.append(ValidationResult("WARNING", rel, f"Could not fetch schema {schema_url}: {e}"))
        return results

    validator = jsonschema.Draft7Validator(schema)
    for error in sorted(validator.iter_errors(data), key=lambda e: str(e.path)):
        path = " > ".join(str(p) for p in error.absolute_path) or "(root)"
        results.append(ValidationResult("ERROR", rel, f"{error.message} (at {path})"))

    return results
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_validator.py -k "schema" -v
```

Expected: all schema tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tab_to_pbi/validator.py tests/test_validator.py
git commit -m "feat: Phase 2 JSON schema validation"
```

---

### Task 5: Phase 3 — semantic cross-reference checks

**Files:**
- Modify: `tab_to_pbi/validator.py`
- Modify: `tests/test_validator.py`

- [ ] **Step 1: Write failing tests for semantic checks**

Add to `tests/test_validator.py`:

```python
from tab_to_pbi.validator import check_semantics

_VISUAL_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.0.0/schema.json"

_VALID_MODEL_BIM = {
    "name": "simple",
    "compatibilityLevel": 1550,
    "model": {
        "culture": "en-US",
        "tables": [
            {
                "name": "Orders",
                "columns": [
                    {"name": "Country", "dataType": "string", "sourceColumn": "Country"},
                ],
                "partitions": [{"name": "Orders", "mode": "import", "source": {"type": "m", "expression": ["let", "in", "x"]}}],
            }
        ],
        "relationships": [],
    },
}

_VALID_PBIR = {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
    "version": "4.0",
    "datasetReference": {"byPath": {"path": "../simple.SemanticModel"}},
}

_VALID_VISUAL = {
    "$schema": _VISUAL_SCHEMA,
    "name": "visual_1",
    "position": {"x": 0, "y": 0, "z": 0, "height": 300, "width": 400, "tabOrder": 0},
    "visual": {
        "visualType": "tableEx",
        "query": {
            "queryState": {
                "Values": {
                    "projections": [
                        {
                            "field": {"Column": {"Expression": {"SourceRef": {"Entity": "Orders"}}, "Property": "Country"}},
                            "queryRef": "Orders.Country",
                            "active": True,
                        }
                    ]
                }
            }
        },
        "objects": {},
    },
}


def _setup_semantic_test(tmp_path, pbir=None, model_bim=None, visual=None):
    report_dir, model_dir = _make_valid_structure(tmp_path)
    (report_dir / "definition.pbir").write_text(json.dumps(pbir or _VALID_PBIR))
    (model_dir / "model.bim").write_text(json.dumps(model_bim or _VALID_MODEL_BIM))
    v_path = report_dir / "definition" / "pages" / "ReportSection1" / "visuals" / "visual_1" / "visual.json"
    v_path.parent.mkdir(parents=True, exist_ok=True)
    v_path.write_text(json.dumps(visual or _VALID_VISUAL))
    return report_dir, model_dir


def test_semantics_clean(tmp_path):
    report_dir, _ = _setup_semantic_test(tmp_path)
    results = check_semantics(report_dir)
    errors = [r for r in results if r.level == "ERROR"]
    assert errors == []


def test_semantics_bypath_missing_model(tmp_path):
    report_dir, model_dir = _setup_semantic_test(tmp_path)
    import shutil
    shutil.rmtree(model_dir)
    results = check_semantics(report_dir)
    assert any("byPath" in r.message and r.level == "ERROR" for r in results)


def test_semantics_unknown_entity(tmp_path):
    bad_visual = {**_VALID_VISUAL}
    bad_visual["visual"] = {
        **_VALID_VISUAL["visual"],
        "query": {"queryState": {"Values": {"projections": [
            {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "NonExistent"}}, "Property": "Country"}}, "queryRef": "x", "active": True}
        ]}}},
    }
    report_dir, _ = _setup_semantic_test(tmp_path, visual=bad_visual)
    results = check_semantics(report_dir)
    assert any("NonExistent" in r.message and r.level == "ERROR" for r in results)


def test_semantics_unknown_column(tmp_path):
    bad_visual = {**_VALID_VISUAL}
    bad_visual["visual"] = {
        **_VALID_VISUAL["visual"],
        "query": {"queryState": {"Values": {"projections": [
            {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "Orders"}}, "Property": "NoSuchCol"}}, "queryRef": "x", "active": True}
        ]}}},
    }
    report_dir, _ = _setup_semantic_test(tmp_path, visual=bad_visual)
    results = check_semantics(report_dir)
    assert any("NoSuchCol" in r.message and r.level == "ERROR" for r in results)


def test_semantics_no_tables_in_model(tmp_path):
    bad_bim = {**_VALID_MODEL_BIM, "model": {**_VALID_MODEL_BIM["model"], "tables": []}}
    report_dir, _ = _setup_semantic_test(tmp_path, model_bim=bad_bim)
    results = check_semantics(report_dir)
    assert any("no tables" in r.message.lower() and r.level == "ERROR" for r in results)


def test_semantics_table_no_partitions(tmp_path):
    bad_bim = {
        **_VALID_MODEL_BIM,
        "model": {**_VALID_MODEL_BIM["model"], "tables": [
            {"name": "Orders", "columns": [], "partitions": []}
        ]},
    }
    report_dir, _ = _setup_semantic_test(tmp_path, model_bim=bad_bim)
    results = check_semantics(report_dir)
    assert any("partition" in r.message.lower() and r.level == "ERROR" for r in results)


def test_semantics_no_relationships_warning(tmp_path):
    report_dir, _ = _setup_semantic_test(tmp_path)
    results = check_semantics(report_dir)
    assert any("relationship" in r.message.lower() and r.level == "WARNING" for r in results)


def test_semantics_visual_no_projections_warning(tmp_path):
    empty_visual = {
        "$schema": _VISUAL_SCHEMA,
        "name": "visual_1",
        "position": {"x": 0, "y": 0, "z": 0, "height": 300, "width": 400, "tabOrder": 0},
        "visual": {"visualType": "tableEx", "query": {"queryState": {}}, "objects": {}},
    }
    report_dir, _ = _setup_semantic_test(tmp_path, visual=empty_visual)
    results = check_semantics(report_dir)
    assert any("projection" in r.message.lower() and r.level == "WARNING" for r in results)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_validator.py -k "semantics" -v
```

Expected: `ImportError` — `check_semantics` not defined yet.

- [ ] **Step 3: Implement check_semantics**

Add to `tab_to_pbi/validator.py`:

```python
def check_semantics(report_dir: Path) -> list[ValidationResult]:
    """Phase 3: cross-file semantic consistency checks."""
    results = []
    model_dir = _find_model_dir(report_dir)

    # Check byPath resolves
    pbir_path = report_dir / "definition.pbir"
    if pbir_path.exists():
        try:
            pbir = json.loads(pbir_path.read_text())
            by_path = pbir.get("datasetReference", {}).get("byPath", {}).get("path")
            if by_path:
                resolved = (report_dir / by_path).resolve()
                if not resolved.is_dir():
                    results.append(ValidationResult(
                        "ERROR", str(pbir_path.relative_to(report_dir.parent)),
                        f"byPath '{by_path}' does not resolve to an existing directory"
                    ))
        except (json.JSONDecodeError, KeyError):
            pass

    # Load model.bim for cross-reference checks
    tables_by_name: dict[str, set[str]] = {}
    partitions_checked = False
    if model_dir and (model_dir / "model.bim").exists():
        try:
            bim = json.loads((model_dir / "model.bim").read_text())
            tables = bim.get("model", {}).get("tables", [])
            rel = str((model_dir / "model.bim").relative_to(report_dir.parent))

            if not tables:
                results.append(ValidationResult("ERROR", rel, "model.bim has no tables"))
            for table in tables:
                tname = table.get("name", "")
                tables_by_name[tname] = {c["name"] for c in table.get("columns", [])}
                if not table.get("partitions"):
                    results.append(ValidationResult(
                        "ERROR", rel, f"Table '{tname}' has no partitions"
                    ))
                else:
                    partitions_checked = True
                    for part in table["partitions"]:
                        expr = part.get("source", {}).get("expression", [])
                        if isinstance(expr, list) and any("Unsupported connection type" in line for line in expr):
                            results.append(ValidationResult(
                                "WARNING", rel,
                                f"Table '{tname}' partition uses unsupported connection type"
                            ))

            relationships = bim.get("model", {}).get("relationships", [])
            if not relationships:
                results.append(ValidationResult(
                    "WARNING", rel, "No relationships defined (expected for single-table Import mode)"
                ))
        except json.JSONDecodeError:
            pass

    # Check visual field references
    defn_dir = report_dir / "definition"
    if (defn_dir / "pages").is_dir():
        for page_dir in (defn_dir / "pages").iterdir():
            if not page_dir.is_dir():
                continue
            visuals_dir = page_dir / "visuals"
            if not visuals_dir.is_dir():
                continue
            for visual_dir in visuals_dir.iterdir():
                if not visual_dir.is_dir():
                    continue
                vpath = visual_dir / "visual.json"
                if not vpath.exists():
                    continue
                rel = str(vpath.relative_to(report_dir.parent))
                try:
                    visual = json.loads(vpath.read_text())
                except json.JSONDecodeError:
                    continue

                projections = _extract_projections(visual)
                if not projections:
                    results.append(ValidationResult(
                        "WARNING", rel, "Visual has no field projections"
                    ))
                    continue

                for proj in projections:
                    col = proj.get("field", {}).get("Column", {})
                    entity = col.get("Expression", {}).get("SourceRef", {}).get("Entity")
                    prop = col.get("Property")
                    if entity and entity not in tables_by_name:
                        results.append(ValidationResult(
                            "ERROR", rel,
                            f"SourceRef.Entity '{entity}' not found in model.bim tables"
                        ))
                    elif entity and prop and prop not in tables_by_name.get(entity, set()):
                        results.append(ValidationResult(
                            "ERROR", rel,
                            f"Column '{prop}' not found in table '{entity}' in model.bim"
                        ))

    return results


def _extract_projections(visual: dict) -> list[dict]:
    """Extract all projections from a visual's queryState."""
    query_state = visual.get("visual", {}).get("query", {}).get("queryState", {})
    projections = []
    for role in query_state.values():
        projections.extend(role.get("projections", []))
    return projections
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_validator.py -k "semantics" -v
```

Expected: all semantic tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tab_to_pbi/validator.py tests/test_validator.py
git commit -m "feat: Phase 3 semantic cross-reference checks"
```

---

### Task 6: Top-level validate() and output formatting

**Files:**
- Modify: `tab_to_pbi/validator.py`
- Modify: `tests/test_validator.py`

- [ ] **Step 1: Write failing integration test**

Add to `tests/test_validator.py`:

```python
from tab_to_pbi.validator import validate

_PBIR_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json"
_VERSION_SCHEMA_URL = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
_REPORT_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/1.0.0/schema.json"
_PAGE_SCHEMA_URL = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.0.0/schema.json"


def _make_fully_valid_structure(tmp_path):
    """Full valid PBIR structure with correct schema-compliant JSON content."""
    report_dir, model_dir = _make_valid_structure(tmp_path)

    (report_dir / "definition.pbir").write_text(json.dumps({
        "$schema": _PBIR_SCHEMA,
        "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{model_dir.name}"}},
    }))
    (report_dir / "definition" / "version.json").write_text(json.dumps({
        "$schema": _VERSION_SCHEMA_URL,
        "version": "1.0.0",
    }))
    (report_dir / "definition" / "report.json").write_text(json.dumps({
        "$schema": _REPORT_SCHEMA,
        "layoutOptimization": "None",
        "themeCollection": {"baseTheme": {"name": "CY24SU06", "reportVersionAtImport": "5.58", "type": "SharedResources"}},
    }))
    (report_dir / "definition" / "pages" / "ReportSection1" / "page.json").write_text(json.dumps({
        "$schema": _PAGE_SCHEMA_URL,
        "name": "ReportSection1",
        "displayName": "Sheet 1",
        "displayOption": "FitToPage",
    }))
    v_path = report_dir / "definition" / "pages" / "ReportSection1" / "visuals" / "visual_1" / "visual.json"
    v_path.parent.mkdir(parents=True, exist_ok=True)
    v_path.write_text(json.dumps({
        "$schema": _VISUAL_SCHEMA,
        "name": "visual_1",
        "position": {"x": 0, "y": 0, "z": 0, "height": 300, "width": 400, "tabOrder": 0},
        "visual": {
            "visualType": "tableEx",
            "query": {"queryState": {"Values": {"projections": [
                {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "Orders"}}, "Property": "Country"}}, "queryRef": "Orders.Country", "active": True}
            ]}}},
            "objects": {},
        },
    }))
    (model_dir / "model.bim").write_text(json.dumps(_VALID_MODEL_BIM))
    return report_dir


def test_validate_fully_valid(tmp_path):
    report_dir = _make_fully_valid_structure(tmp_path)
    results = validate(report_dir)
    errors = [r for r in results if r.level == "ERROR"]
    assert errors == [], f"Unexpected errors: {errors}"


def test_validate_returns_errors_on_broken_structure(tmp_path):
    report_dir, _ = _make_valid_structure(tmp_path)
    (report_dir / "definition.pbir").unlink()
    results = validate(report_dir)
    assert any(r.level == "ERROR" for r in results)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_validator.py::test_validate_fully_valid -v
```

Expected: `ImportError` — `validate` not defined yet.

- [ ] **Step 3: Implement validate() and _print_results()**

Add to `tab_to_pbi/validator.py`:

```python
def validate(report_dir: Path, cache_dir: Path = _DEFAULT_CACHE) -> list[ValidationResult]:
    """Run all three validation phases. Returns combined results."""
    results = check_presence(report_dir)
    errors = [r for r in results if r.level == "ERROR"]
    if errors:
        return results  # Don't run schema/semantic if structure is broken
    results.extend(check_schemas(report_dir, cache_dir))
    schema_errors = [r for r in results if r.level == "ERROR"]
    if not schema_errors:
        results.extend(check_semantics(report_dir))
    return results


def print_results(report_dir: Path, results: list[ValidationResult]) -> None:
    """Print validation results to stdout."""
    print(f"Validating {report_dir}...")
    if not results:
        print("All checks passed (0 errors, 0 warnings).")
        return
    for r in results:
        print(f"\n  {r.level:<7} {r.file}")
        print(f"          {r.message}")
    errors = sum(1 for r in results if r.level == "ERROR")
    warnings = sum(1 for r in results if r.level == "WARNING")
    print(f"\n{errors} error{'s' if errors != 1 else ''}, {warnings} warning{'s' if warnings != 1 else ''}")
    if errors:
        print("Validation failed.")
    else:
        print("Validation passed with warnings.")
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_validator.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tab_to_pbi/validator.py tests/test_validator.py
git commit -m "feat: top-level validate() and print_results()"
```

---

### Task 7: Standalone CLI entry point

**Files:**
- Modify: `tab_to_pbi/validator.py`

- [ ] **Step 1: Add CLI block to validator.py**

Append to the bottom of `tab_to_pbi/validator.py`:

```python
if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: uv run tab_to_pbi/validator.py <path/to/Report-folder>")
        sys.exit(1)
    _report_dir = Path(sys.argv[1])
    if not _report_dir.is_dir():
        print(f"Error: {_report_dir} is not a directory")
        sys.exit(1)
    _results = validate(_report_dir)
    print_results(_report_dir, _results)
    sys.exit(1 if any(r.level == "ERROR" for r in _results) else 0)
```

- [ ] **Step 2: Run standalone against generated output**

```bash
uv run tab_to_pbi/validator.py output/simple.Report
```

Expected: output lists results; exits 0 if no errors.

- [ ] **Step 3: Verify exit code**

```bash
uv run tab_to_pbi/validator.py output/simple.Report; echo "Exit: $?"
```

Expected: `Exit: 0`

- [ ] **Step 4: Commit**

```bash
git add tab_to_pbi/validator.py
git commit -m "feat: standalone CLI entry point for validator"
```

---

### Task 8: Integrate validator into main.py pipeline

**Files:**
- Modify: `tab_to_pbi/main.py`

- [ ] **Step 1: Add validate call to main()**

Edit `tab_to_pbi/main.py`. Replace the current `main()` function with:

```python
def main():
    if len(sys.argv) != 2:
        print("Usage: uv run tab_to_pbi/main.py <path/to/workbook.twb>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    workbook = parse(input_path)
    transformed = transform(workbook)
    report_path = generate(transformed, output_dir)

    report_file = output_dir / f"{input_path.stem}.migration_report.json"
    report_file.write_text(json.dumps(transformed.get("report", {}), indent=2))

    print(f"Output: {report_path}")
    print(f"Report: {report_file}")

    from tab_to_pbi.validator import validate, print_results
    results = validate(report_path)
    print()
    print_results(report_path, results)
    if any(r.level == "ERROR" for r in results):
        sys.exit(1)
```

- [ ] **Step 2: Run full pipeline and verify validator output appears**

```bash
rm -rf output/ && uv run tab_to_pbi/main.py input/simple.twb
```

Expected: pipeline completes, validator output printed, exit 0.

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tab_to_pbi/main.py
git commit -m "feat: integrate validator into pipeline — exit 1 on validation errors"
```
