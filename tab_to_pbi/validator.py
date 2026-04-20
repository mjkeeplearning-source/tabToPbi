"""Validate PBIR output folder structure, JSON schemas, and semantic consistency."""

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import jsonschema

_SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report"
_DEFAULT_CACHE = Path(".pbir_schema_cache")

SCHEMAS = {
    "version.json": f"{_SCHEMA_BASE}/definition/versionMetadata/1.0.0/schema.json",
    "pages.json": f"{_SCHEMA_BASE}/definition/pagesMetadata/1.0.0/schema.json",
    "report.json": f"{_SCHEMA_BASE}/definition/report/3.2.0/schema.json",
    "page.json": f"{_SCHEMA_BASE}/definition/page/2.1.0/schema.json",
    "visual.json": f"{_SCHEMA_BASE}/definition/visualContainer/1.0.0/schema.json",
}


@dataclass
class ValidationResult:
    level: str    # "ERROR" or "WARNING"
    file: str     # relative path shown in output
    message: str


def _find_model_dir(report_dir: Path) -> Path | None:
    """Find the matching sibling SemanticModel directory (same stem as report)."""
    stem = report_dir.name.removesuffix(".Report")
    exact = report_dir.parent / f"{stem}.SemanticModel"
    if exact.is_dir():
        return exact
    candidates = list(report_dir.parent.glob("*.SemanticModel"))
    return candidates[0] if candidates else None


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


def check_presence(report_dir: Path) -> list[ValidationResult]:
    """Phase 1: verify all required files and folders exist."""
    results = []

    def err(msg: str) -> None:
        results.append(ValidationResult("ERROR", str(report_dir), msg))

    model_dir = _find_model_dir(report_dir)

    if not (report_dir / "definition.pbir").exists():
        err("Missing required file: definition.pbir")

    defn_dir = report_dir / "definition"
    if not defn_dir.is_dir():
        err("Missing required folder: definition/")
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
    elif not (pages_dir / "pages.json").exists():
        err("Missing required file: definition/pages/pages.json")
    else:
        for page_dir in pages_dir.iterdir():
            if page_dir.is_dir() and not (page_dir / "page.json").exists():
                err(f"Missing required file: {page_dir.relative_to(report_dir.parent)}/page.json")

    if model_dir is None:
        err("Missing SemanticModel directory (expected sibling of Report folder)")
    else:
        if not (model_dir / "definition.pbism").exists():
            err("Missing required file: definition.pbism")
        has_bim = (model_dir / "model.bim").exists()
        has_tmdl = (model_dir / "definition" / "model.tmdl").exists()
        if not has_bim and not has_tmdl:
            err("Missing semantic model: expected definition/model.tmdl (TMDL) or model.bim (TMSL)")

    return results


def check_schemas(report_dir: Path, cache_dir: Path = _DEFAULT_CACHE) -> list[ValidationResult]:
    """Phase 2: validate each required JSON file against its declared MS schema."""
    results = []
    defn_dir = report_dir / "definition"

    files_to_check = [
        defn_dir / "version.json",
        defn_dir / "report.json",
    ]
    pages_dir = defn_dir / "pages"
    if pages_dir.is_dir():
        files_to_check.append(pages_dir / "pages.json")
        for page_dir in pages_dir.iterdir():
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


def check_semantics(report_dir: Path) -> list[ValidationResult]:
    """Phase 3: cross-file semantic consistency checks."""
    results = []
    model_dir = _find_model_dir(report_dir)

    # Check byPath resolves to an existing directory
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
                        f"byPath '{by_path}' does not resolve to an existing directory",
                    ))
        except (json.JSONDecodeError, KeyError):
            pass

    # Load table/column names for cross-reference checks (TMDL or TMSL)
    tables_by_name: dict[str, set[str]] = {}
    if model_dir:
        tmdl_tables_dir = model_dir / "definition" / "tables"
        bim_path = model_dir / "model.bim"
        if tmdl_tables_dir.is_dir():
            tables_by_name = _load_tmdl_tables(tmdl_tables_dir)
        elif bim_path.exists():
            try:
                bim = json.loads(bim_path.read_text())
                rel = str(bim_path.relative_to(report_dir.parent))
                for table in bim.get("model", {}).get("tables", []):
                    tname = table.get("name", "")
                    tables_by_name[tname] = {c["name"] for c in table.get("columns", [])}
                if not bim.get("model", {}).get("relationships"):
                    results.append(ValidationResult(
                        "WARNING", rel, "No relationships defined (expected for single-table Import mode)"
                    ))
            except json.JSONDecodeError:
                pass

    # Check visual field references against model.bim
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
                    results.append(ValidationResult("WARNING", rel, "Visual has no field projections"))
                    continue

                for proj in projections:
                    col = proj.get("field", {}).get("Column", {})
                    entity = col.get("Expression", {}).get("SourceRef", {}).get("Entity")
                    prop = col.get("Property")
                    if entity and entity not in tables_by_name:
                        results.append(ValidationResult(
                            "ERROR", rel, f"SourceRef.Entity '{entity}' not found in model.bim tables"
                        ))
                    elif entity and prop and prop not in tables_by_name.get(entity, set()):
                        results.append(ValidationResult(
                            "ERROR", rel, f"Column '{prop}' not found in table '{entity}' in model.bim"
                        ))

    return results


def _load_tmdl_tables(tables_dir: Path) -> dict[str, set[str]]:
    """Parse TMDL table files to extract {table_name: {column_names}} for cross-reference."""
    import re
    tables: dict[str, set[str]] = {}
    for tmdl_file in tables_dir.glob("*.tmdl"):
        text = tmdl_file.read_text(encoding="utf-8")
        table_match = re.search(r"^table\s+'?([^'\n]+)'?", text, re.MULTILINE)
        if not table_match:
            continue
        table_name = table_match.group(1).strip("'")
        columns = {
            m.group(1).strip("'")
            for m in re.finditer(r"^\s+column\s+'?([^'\n]+)'?", text, re.MULTILINE)
        }
        tables[table_name] = columns
    return tables


def _extract_projections(visual: dict) -> list[dict]:
    """Extract all projections from a visual's queryState."""
    query_state = visual.get("visual", {}).get("query", {}).get("queryState", {})
    projections = []
    for role in query_state.values():
        projections.extend(role.get("projections", []))
    return projections


def validate(report_dir: Path, cache_dir: Path = _DEFAULT_CACHE) -> list[ValidationResult]:
    """Run all three validation phases. Returns combined results."""
    results = check_presence(report_dir)
    if any(r.level == "ERROR" for r in results):
        return results
    results.extend(check_schemas(report_dir, cache_dir))
    if not any(r.level == "ERROR" for r in results):
        results.extend(check_semantics(report_dir))
    return results


def print_results(report_dir: Path, results: list[ValidationResult]) -> None:
    """Print validation results to stdout."""
    print(f"Validating {report_dir}...")
    if not results:
        print("All checks passed (0 errors, 0 warnings).")
        return
    errors = sum(1 for r in results if r.level == "ERROR")
    warnings = sum(1 for r in results if r.level == "WARNING")
    for r in results:
        print(f"\n  {r.level:<7} {r.file}")
        print(f"          {r.message}")
    print(f"\n{errors} error{'s' if errors != 1 else ''}, {warnings} warning{'s' if warnings != 1 else ''}")
    if errors:
        print("Validation failed.")
    else:
        print("All checks passed (0 errors, 0 warnings)." if warnings == 0 else "Validation passed with warnings.")


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
