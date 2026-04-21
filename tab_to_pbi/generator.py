"""Write PBIR folder structure from transformed workbook dict."""

import json
from pathlib import Path

MARK_TO_VISUAL = {
    "Automatic": "tableEx",
    "Bar": "barChart",
    "Column": "columnChart",
    "Line": "lineChart",
    "Area": "areaChart",
    "Pie": "pieChart",
    "Circle": "scatterChart",
    "Shape": "scatterChart",
    "Polygon": "filledMap",
    "Multipolygon": "filledMap",
    "PolyLine": "map",
    "Text": "tableEx",
}

_SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report"


def generate(transformed: dict, output_dir: Path, data_dir: Path = Path("data")) -> Path:
    """Write PBIR SemanticModel and Report files. Returns the Report folder path."""
    name = transformed["name"]
    report_dir = output_dir / f"{name}.Report"
    model_dir = output_dir / f"{name}.SemanticModel"
    definition_dir = report_dir / "definition"

    report_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    definition_dir.mkdir(parents=True, exist_ok=True)

    _write_definition_pbism(model_dir)
    _write_tmdl_model(model_dir, transformed, data_dir)
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


def _tmdl_id(name: str) -> str:
    """Quote a TMDL identifier that contains spaces or special characters."""
    if any(c in name for c in " ()/-.,"):
        return f"'{name}'"
    return name


def _write_tmdl_model(model_dir: Path, transformed: dict, data_dir: Path) -> None:
    """Write TMDL semantic model: definition/model.tmdl + definition/tables/<name>.tmdl."""
    defn_dir = model_dir / "definition"
    tables_dir = defn_dir / "tables"
    defn_dir.mkdir(exist_ok=True)
    tables_dir.mkdir(exist_ok=True)

    # Remove legacy TMSL file if present
    legacy_bim = model_dir / "model.bim"
    if legacy_bim.exists():
        legacy_bim.unlink()

    name = transformed["name"]
    database_tmdl = f"database '{name}'\n\tcompatibilityLevel: 1550\n"
    (defn_dir / "database.tmdl").write_text(database_tmdl, encoding="utf-8")

    rels = transformed.get("relationships", [])
    rel_lines = []
    for r in rels:
        rel_name = f"{r['from_table']}_{r['from_column']} -> {r['to_table']}_{r['to_column']}"
        rel_lines += [
            f"\trelationship '{rel_name}'",
            f"\t\tfromColumn: {r['from_table']}.{r['from_column']}",
            f"\t\ttoColumn: {r['to_table']}.{r['to_column']}",
            "",
        ]

    has_dq = any(
        t.get("connection", {}).get("storage_mode") == "directQuery"
        for t in transformed.get("tables", [])
    )
    model_tmdl = (
        "model Model\n"
        "\tculture: en-US\n"
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
    )
    if has_dq:
        model_tmdl += "\tdefaultMode: directQuery\n"
    if rel_lines:
        model_tmdl += "\n" + "\n".join(rel_lines)
    (defn_dir / "model.tmdl").write_text(model_tmdl, encoding="utf-8")

    measures_by_table: dict[str, list] = {}
    for m in transformed.get("measures", []):
        measures_by_table.setdefault(m["table"], []).append(m)

    for table in transformed.get("tables", []):
        _write_tmdl_table(tables_dir, table, data_dir, measures_by_table.get(table["name"], []))


def _write_tmdl_table(tables_dir: Path, table: dict, data_dir: Path, measures: list | None = None) -> None:
    """Write one TMDL table file."""
    name = table["name"]
    qname = _tmdl_id(name)
    lines = [f"table {qname}", ""]

    for col in table["columns"]:
        lines.append(f"\tcolumn {_tmdl_id(col['name'])}")
        lines.append(f"\t\tdataType: {col['dataType']}")
        lines.append(f"\t\tsourceColumn: {col['name']}")
        lines.append("")

    for m in measures:
        lines.append(f"\tmeasure {_tmdl_id(m['name'])} = {m['dax']}")
        lines.append("")

    if measures is None:
        measures = []
    conn = table["connection"]
    storage_mode = conn.get("storage_mode", "import")
    expr_lines = _build_m_expression(conn, data_dir)
    lines.append(f"\tpartition {qname} = m")
    lines.append(f"\t\tmode: {storage_mode}")
    lines.append("\t\tsource =")
    for line in expr_lines:
        lines.append(f"\t\t\t{line}")
    lines.append("")

    safe_name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    (tables_dir / f"{safe_name}.tmdl").write_text("\n".join(lines), encoding="utf-8")


def _build_m_expression(conn: dict, data_dir: Path) -> list[str]:
    """Build Power Query M expression lines from connection info."""
    conn_type = conn.get("type", "")
    stem = Path(conn.get("filename", "")).stem
    xlsx = data_dir / f"{stem}.xlsx"
    xls = data_dir / f"{stem}.xls"
    resolved = xlsx if xlsx.exists() else xls
    filename = resolved.resolve().as_posix()
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

    if conn_type == "postgres":
        server = conn.get("server", "")
        dbname = conn.get("dbname", "")
        custom_sql = conn.get("custom_sql", "")
        if custom_sql:
            escaped_sql = custom_sql.replace('"', '""')
            return [
                "let",
                f'    Source = PostgreSQL.Database("{server}", "{dbname}"),',
                f'    nav = Value.NativeQuery(Source, "{escaped_sql}", null, [EnableFolding=true])',
                "in",
                "    nav",
            ]
        schema = conn.get("schema", "")
        table = conn.get("table", "")
        return [
            "let",
            f'    Source = PostgreSQL.Database("{server}", "{dbname}"),',
            f'    nav = Source{{[Schema="{schema}", Item="{table}"]}}[Data]',
            "in",
            "    nav",
        ]

    return [f'error "Unsupported connection type: {conn_type}"']


def _write_definition_pbir(report_dir: Path, model_name: str) -> None:
    """Write definition.pbir at report root referencing the SemanticModel."""
    content = {
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
        "version": "2.0.0",
    }
    (definition_dir / "version.json").write_text(json.dumps(content, indent=2))


def _write_report_json(definition_dir: Path) -> None:
    """Write definition/report.json matching PBI Desktop 2.152 format."""
    content = {
        "$schema": f"{_SCHEMA_BASE}/definition/report/3.2.0/schema.json",
        "themeCollection": {
            "baseTheme": {
                "name": "CY26SU02",
                "reportVersionAtImport": {
                    "visual": "2.6.0",
                    "report": "3.1.0",
                    "page": "2.3.0",
                },
                "type": "SharedResources",
            }
        },
        "objects": {
            "section": [
                {
                    "properties": {
                        "verticalAlignment": {
                            "expr": {"Literal": {"Value": "'Top'"}}
                        }
                    }
                }
            ]
        },
        "settings": {
            "useStylableVisualContainerHeader": True,
            "exportDataMode": "AllowSummarized",
            "defaultDrillFilterOtherVisuals": True,
            "allowChangeFilterTypes": True,
            "useEnhancedTooltips": True,
            "useDefaultAggregateDisplayName": True,
        },
    }
    (definition_dir / "report.json").write_text(json.dumps(content, indent=2))


def _write_pages(definition_dir: Path, transformed: dict) -> None:
    """Write one page folder per sheet under definition/pages/, plus pages.json manifest."""
    pages_dir = definition_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    section_ids = []
    for i, visual_info in enumerate(transformed.get("visuals", [])):
        section_id = f"ReportSection{i + 1}"
        section_ids.append(section_id)
        page_dir = pages_dir / section_id
        page_dir.mkdir(exist_ok=True)
        _write_page(page_dir, visual_info, i)
    _write_pages_manifest(pages_dir, section_ids)


def _write_pages_manifest(pages_dir: Path, section_ids: list[str]) -> None:
    """Write definition/pages/pages.json required by PBI Desktop for page discovery."""
    content = {
        "$schema": f"{_SCHEMA_BASE}/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": section_ids,
        "activePageName": section_ids[0] if section_ids else "",
    }
    (pages_dir / "pages.json").write_text(json.dumps(content, indent=2))


def _write_page(page_dir: Path, visual_info: dict, ordinal: int) -> None:
    """Write page.json and visuals for this sheet."""
    page = {
        "$schema": f"{_SCHEMA_BASE}/definition/page/2.1.0/schema.json",
        "name": page_dir.name,
        "displayName": visual_info["name"],
        "displayOption": "FitToPage",
        "height": 720,
        "width": 1280,
    }
    (page_dir / "page.json").write_text(json.dumps(page, indent=2))

    has_fields = visual_info.get("row_fields") or visual_info.get("col_fields")
    if has_fields and visual_info.get("table"):
        visuals_dir = page_dir / "visuals"
        visuals_dir.mkdir(exist_ok=True)
        visual_dir = visuals_dir / f"visual_{ordinal + 1}"
        visual_dir.mkdir(exist_ok=True)
        _write_visual(visual_dir, visual_info)


# Maps visual type to (role1, role2, shelf_for_role1, shelf_for_role2)
# shelf values: "row" or "col" — which Tableau shelf feeds each PBI role
_VISUAL_ROLES = {
    "barChart":    ("Category", "Y",        "row", "col"),
    "columnChart": ("Category", "Y",        "col", "row"),
    "lineChart":   ("Category", "Y",        "col", "row"),
    "areaChart":   ("Category", "Y",        "col", "row"),
    "pieChart":    ("Legend",   "Values",   "row", "col"),
    "scatterChart":("X",        "Y",        "col", "row"),
    "map":         ("Location", "Size",     "row", "col"),
    "filledMap":   ("Location", "Size",     "row", "col"),
}


def _make_projection(default_table: str, field: dict | str) -> dict:
    """Build a field projection, using per-field table when available."""
    if isinstance(field, dict):
        name = field["name"]
        field_type = "Measure" if field.get("is_measure") else "Column"
        table_name = field.get("table") or default_table
    else:
        name = field
        field_type = "Column"
        table_name = default_table
    return {
        "field": {
            field_type: {
                "Expression": {"SourceRef": {"Entity": table_name}},
                "Property": name,
            }
        },
        "queryRef": f"{table_name}.{name}",
        "active": True,
    }


def _write_visual(visual_dir: Path, visual_info: dict) -> None:
    """Write visual.json with role-based field projections per visual type."""
    visual_type = MARK_TO_VISUAL.get(visual_info["mark_type"], "tableEx")
    table_name = visual_info["table"]
    row_fields = visual_info.get("row_fields", [])
    col_fields = visual_info.get("col_fields", [])

    if visual_type in _VISUAL_ROLES:
        cat_role, val_role, cat_shelf, val_shelf = _VISUAL_ROLES[visual_type]
        cat_fields = row_fields if cat_shelf == "row" else col_fields
        val_fields = col_fields if val_shelf == "col" else row_fields
        query_state = {
            cat_role: {"projections": [_make_projection(table_name, f) for f in cat_fields]},
            val_role: {"projections": [_make_projection(table_name, f) for f in val_fields]},
        }
    else:
        # tableEx and fallback: all fields under Values
        all_fields = row_fields + [f for f in col_fields if f not in row_fields]
        query_state = {
            "Values": {"projections": [_make_projection(table_name, f) for f in all_fields]}
        }

    visual = {
        "$schema": f"{_SCHEMA_BASE}/definition/visualContainer/1.0.0/schema.json",
        "name": visual_dir.name,
        "position": {"x": 20, "y": 20, "z": 0, "height": 360, "width": 560, "tabOrder": 0},
        "visual": {
            "visualType": visual_type,
            "query": {"queryState": query_state},
        },
    }
    (visual_dir / "visual.json").write_text(json.dumps(visual, indent=2))
