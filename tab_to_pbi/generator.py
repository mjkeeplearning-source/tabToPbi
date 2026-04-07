"""Write PBIR folder structure from transformed workbook dict."""

import json
from pathlib import Path


def generate(transformed: dict, output_dir: Path) -> Path:
    """Write PBIR SemanticModel files. Returns the Report folder path."""
    name = transformed["name"]
    report_dir = output_dir / f"{name}.Report"
    model_dir = output_dir / f"{name}.SemanticModel"
    report_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    _write_definition_pbism(model_dir)
    _write_model_bim(model_dir, transformed)

    return report_dir


def _write_definition_pbism(model_dir: Path) -> None:
    """Write definition.pbism."""
    content = {"version": "4.0", "settings": {}}
    (model_dir / "definition.pbism").write_text(json.dumps(content, indent=2))


def _write_model_bim(model_dir: Path, transformed: dict) -> None:
    """Write model.bim in TMSL format."""
    tables = [_build_table(t) for t in transformed.get("tables", [])]
    bim = {
        "compatibilityLevel": 1550,
        "model": {
            "name": transformed["name"],
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
                "source": {
                    "type": "m",
                    "expression": expression,
                },
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
