"""Tests for PBIR validator."""
import json
from pathlib import Path
import pytest
from tab_to_pbi.validator import ValidationResult, load_schema, check_presence, check_schemas


def test_validation_result_fields():
    r = ValidationResult(level="ERROR", file="foo/bar.json", message="missing field")
    assert r.level == "ERROR"
    assert r.file == "foo/bar.json"
    assert r.message == "missing field"


def test_load_schema_returns_dict(tmp_path):
    url = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
    cache_dir = tmp_path / ".pbir_schema_cache"
    schema = load_schema(url, cache_dir)
    assert isinstance(schema, dict)
    assert "$schema" in schema or "properties" in schema


def test_load_schema_uses_cache(tmp_path):
    url = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
    cache_dir = tmp_path / ".pbir_schema_cache"
    schema1 = load_schema(url, cache_dir)
    schema2 = load_schema(url, cache_dir)
    assert schema1 == schema2
    assert any(cache_dir.iterdir())


# --- Helpers ---

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


# --- Presence tests ---

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


# --- Schema validation tests ---

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
