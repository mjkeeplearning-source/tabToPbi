"""Write PBIR folder structure from transformed workbook dict."""

import json
from pathlib import Path

MARK_TO_VISUAL = {
    "Automatic": "tableEx",
    "Bar": "barChart",
    "Line": "lineChart",
    "Text": "tableEx",
}

_SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report"


def generate(transformed: dict, output_dir: Path) -> Path:
    """Write PBIR SemanticModel and Report files. Returns the Report folder path."""
    name = transformed["name"]
    report_dir = output_dir / f"{name}.Report"
    model_dir = output_dir / f"{name}.SemanticModel"
    definition_dir = report_dir / "definition"

    report_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    definition_dir.mkdir(parents=True, exist_ok=True)

    _write_definition_pbism(model_dir)
    _write_model_bim(model_dir, transformed)
    _write_definition_pbir(report_dir, name)
    _write_version_json(definition_dir)
    _write_report_json(definition_dir)
    _write_pages(definition_dir, transformed)

    return report_dir


def _write_definition_pbism(model_dir: Path) -> None:
    """Write definition.pbism."""
    (model_dir / "definition.pbism").write_text(
        json.dumps({"version": "4.0", "settings": {}}, indent=2)
    )


def _write_model_bim(model_dir: Path, transformed: dict) -> None:
    """Write model.bim in TMSL format."""
    tables = [_build_table(t) for t in transformed.get("tables", [])]
    bim = {
        "name": transformed["name"],
        "compatibilityLevel": 1550,
        "model": {
            "culture": "en-US",
            "dataAccessOptions": {
                "legacyRedirects": True,
                "returnErrorValuesAsNull": True,
            },
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "relationships": [],
            "tables": tables,
        },
    }
    (model_dir / "model.bim").write_text(json.dumps(bim, indent=2))


def _build_table(table: dict) -> dict:
    """Build a TMSL table entry from a transformed datasource."""
    expression = _build_m_expression(table["connection"])
    return {
        "name": table["name"],
        "columns": table["columns"],
        "partitions": [
            {
                "name": table["name"],
                "mode": "import",
                "source": {"type": "m", "expression": expression},
            }
        ],
    }


def _build_m_expression(conn: dict) -> list[str]:
    """Build Power Query M expression lines from connection info."""
    conn_type = conn.get("type", "")
    filename = conn.get("filename", "").replace("\\", "/")
    table_name = conn.get("table_name", "")
    safe_var = table_name.replace(" ", "_").replace("-", "_")
    escaped_table = table_name.replace('"', '""')

    if conn_type == "excel-direct":
        return [
            "let",
            f'    Source = Excel.Workbook(File.Contents("{filename}"), null, true),',
            f'    {safe_var}_Sheet = Source{{[Item="{escaped_table}",Kind="Sheet"]}}[Data],',
            f'    #"Promoted Headers" = Table.PromoteHeaders({safe_var}_Sheet, [PromoteAllScalars=true])',
            "in",
            '    #"Promoted Headers"',
        ]

    return [f'error "Unsupported connection type: {conn_type}"']


def _write_definition_pbir(report_dir: Path, model_name: str) -> None:
    """Write definition.pbir at report root referencing the SemanticModel."""
    content = {
        "$schema": f"{_SCHEMA_BASE}/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {
            "byPath": {"path": f"../{model_name}.SemanticModel"}
        },
    }
    (report_dir / "definition.pbir").write_text(json.dumps(content, indent=2))


def _write_version_json(definition_dir: Path) -> None:
    """Write definition/version.json."""
    content = {
        "$schema": f"{_SCHEMA_BASE}/definition/versionMetadata/1.0.0/schema.json",
        "version": "1.0.0",
    }
    (definition_dir / "version.json").write_text(json.dumps(content, indent=2))


def _write_report_json(definition_dir: Path) -> None:
    """Write definition/report.json with required fields."""
    content = {
        "$schema": f"{_SCHEMA_BASE}/definition/report/1.0.0/schema.json",
        "layoutOptimization": "None",
        "themeCollection": {
            "baseTheme": {
                "name": "CY24SU06",
                "reportVersionAtImport": "5.58",
                "type": "SharedResources",
            }
        },
    }
    (definition_dir / "report.json").write_text(json.dumps(content, indent=2))


def _write_pages(definition_dir: Path, transformed: dict) -> None:
    """Write one page folder per sheet under definition/pages/."""
    pages_dir = definition_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    for i, visual_info in enumerate(transformed.get("visuals", [])):
        section_id = f"ReportSection{i + 1}"
        page_dir = pages_dir / section_id
        page_dir.mkdir(exist_ok=True)
        _write_page(page_dir, visual_info, i)


def _write_page(page_dir: Path, visual_info: dict, ordinal: int) -> None:
    """Write page.json and visuals for this sheet."""
    page = {
        "$schema": f"{_SCHEMA_BASE}/definition/page/1.0.0/schema.json",
        "name": page_dir.name,
        "displayName": visual_info["name"],
        "displayOption": "FitToPage",
    }
    (page_dir / "page.json").write_text(json.dumps(page, indent=2))

    if visual_info.get("fields") and visual_info.get("table"):
        visuals_dir = page_dir / "visuals"
        visuals_dir.mkdir(exist_ok=True)
        visual_dir = visuals_dir / f"visual_{ordinal + 1}"
        visual_dir.mkdir(exist_ok=True)
        _write_visual(visual_dir, visual_info)


def _write_visual(visual_dir: Path, visual_info: dict) -> None:
    """Write visual.json for a table visual referencing the sheet's fields."""
    visual_type = MARK_TO_VISUAL.get(visual_info["mark_type"], "tableEx")
    table_name = visual_info["table"]

    projections = [
        {
            "field": {
                "Column": {
                    "Expression": {"SourceRef": {"Entity": table_name}},
                    "Property": field,
                }
            },
            "queryRef": f"{table_name}.{field}",
            "active": True,
        }
        for field in visual_info["fields"]
    ]

    visual = {
        "$schema": f"{_SCHEMA_BASE}/definition/visualContainer/1.0.0/schema.json",
        "name": visual_dir.name,
        "position": {
            "x": 20,
            "y": 20,
            "z": 0,
            "height": 360,
            "width": 560,
            "tabOrder": 0,
        },
        "visual": {
            "visualType": visual_type,
            "query": {
                "queryState": {
                    "Values": {"projections": projections}
                }
            },
            "objects": {},
        },
    }
    (visual_dir / "visual.json").write_text(json.dumps(visual, indent=2))
