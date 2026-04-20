"""Tests for PBIR validator."""
import json
from pathlib import Path
import pytest
from tab_to_pbi.validator import ValidationResult, load_schema, check_presence, check_schemas, check_semantics, validate


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
    (pages_dir.parent / "pages.json").write_text("{}")
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


# --- Semantic tests ---

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
    bad_visual = {**_VALID_VISUAL, "visual": {
        **_VALID_VISUAL["visual"],
        "query": {"queryState": {"Values": {"projections": [
            {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "NonExistent"}}, "Property": "Country"}}, "queryRef": "x", "active": True}
        ]}}},
    }}
    report_dir, _ = _setup_semantic_test(tmp_path, visual=bad_visual)
    results = check_semantics(report_dir)
    assert any("NonExistent" in r.message and r.level == "ERROR" for r in results)


def test_semantics_unknown_column(tmp_path):
    bad_visual = {**_VALID_VISUAL, "visual": {
        **_VALID_VISUAL["visual"],
        "query": {"queryState": {"Values": {"projections": [
            {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "Orders"}}, "Property": "NoSuchCol"}}, "queryRef": "x", "active": True}
        ]}}},
    }}
    report_dir, _ = _setup_semantic_test(tmp_path, visual=bad_visual)
    results = check_semantics(report_dir)
    assert any("NoSuchCol" in r.message and r.level == "ERROR" for r in results)


def test_semantics_no_tables_in_model(tmp_path):
    bad_bim = {**_VALID_MODEL_BIM, "model": {**_VALID_MODEL_BIM["model"], "tables": []}}
    report_dir, _ = _setup_semantic_test(tmp_path, model_bim=bad_bim)
    results = check_semantics(report_dir)
    assert any("not found" in r.message.lower() and r.level == "ERROR" for r in results)


def test_semantics_table_no_columns(tmp_path):
    bad_bim = {**_VALID_MODEL_BIM, "model": {**_VALID_MODEL_BIM["model"], "tables": [
        {"name": "Orders", "columns": [], "partitions": []}
    ]}}
    report_dir, _ = _setup_semantic_test(tmp_path, model_bim=bad_bim)
    results = check_semantics(report_dir)
    # Visual references Country which is not in the empty column list
    assert any("Country" in r.message and r.level == "ERROR" for r in results)


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


# --- Integration tests ---

_PBIR_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json"
_VERSION_SCHEMA_URL = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
_REPORT_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/1.0.0/schema.json"
_PAGE_SCHEMA_URL = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.0.0/schema.json"


def _make_fully_valid_structure(tmp_path):
    """Full valid PBIR structure with schema-compliant JSON content."""
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
    (report_dir / "definition" / "pages" / "pages.json").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": ["ReportSection1"],
        "activePageName": "ReportSection1",
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
