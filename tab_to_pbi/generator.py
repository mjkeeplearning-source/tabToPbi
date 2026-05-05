"""Write PBIR folder structure from transformed workbook dict."""

import hashlib
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

# Maps Tableau aggregation prefix → PBI semantic query Aggregation.Function integer
_PBI_AGG_FUNC = {
    "sum": 0,
    "avg": 1,
    "average": 1,
    "cntd": 2,
    "ctd": 2,
    "min": 3,
    "max": 4,
    "cnt": 5,
    "median": 6,
}

# Maps PBI/TMDL dataType → Power Query M type literal
_M_TYPE_MAP = {
    "string":   "type text",
    "int64":    "Int64.Type",
    "double":   "Decimal.Type",
    "dateTime": "type datetime",
    "boolean":  "type logical",
}


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
    _write_report_json(definition_dir, transformed.get("datasource_filters", []))
    _write_pages(definition_dir, transformed)

    return report_dir


def _format_literal(value: str) -> str:
    """Format a Tableau filter value string as a PBI semantic query literal."""
    v = value.strip()
    # Tableau date-only: #2023-01-03#  → date'2023-01-03'
    # Tableau datetime:  #2023-01-03 12:00:00#  → datetime'2023-01-03T12:00:00'
    if v.startswith("#") and v.endswith("#"):
        inner = v.strip("#").strip()
        if " " in inner:
            return f"datetime'{inner.replace(' ', 'T')}'"
        return f"date'{inner}'"
    try:
        float_val = float(v)
        int_val = int(float_val)
        return f"{v}L" if int_val == float_val and "." not in v else f"{v}D"
    except ValueError:
        return f"'{v}'"


def _build_filter_entry(f: dict, idx: int) -> dict | None:
    """Build one PBI filterConfig entry from an enriched filter dict."""
    field_name = f["field"]
    table_name = f.get("table", "")
    cls = f["class"]
    if not table_name:
        return None

    filter_id = hashlib.md5(f"{field_name}_{cls}_{idx}".encode()).hexdigest()[:20]
    field_ref = {
        "Column": {
            "Expression": {"SourceRef": {"Entity": table_name}},
            "Property": field_name,
        }
    }
    col_expr = {
        "Column": {
            "Expression": {"SourceRef": {"Source": "f"}},
            "Property": field_name,
        }
    }
    from_clause = [{"Name": "f", "Entity": table_name, "Type": 0}]

    if cls == "categorical":
        values = f.get("values", [])
        if not values:
            return None  # level-members only — no restriction to migrate
        condition = {
            "In": {
                "Expressions": [col_expr],
                "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values],
            }
        }
        filter_type = "Categorical"
        where = [{"Condition": condition}]
    elif cls == "quantitative":
        agg_prefix = f.get("agg_prefix")
        min_val = f.get("min", "")
        max_val = f.get("max", "")
        if agg_prefix and agg_prefix in _PBI_AGG_FUNC:
            # Post-aggregation filter: use Aggregation expression + Advanced type
            agg_func = _PBI_AGG_FUNC[agg_prefix]
            agg_expr = {
                "Aggregation": {
                    "Expression": col_expr,
                    "Function": agg_func,
                }
            }
            agg_field_ref = {
                "Aggregation": {
                    "Expression": {
                        "Column": {
                            "Expression": {"SourceRef": {"Entity": table_name}},
                            "Property": field_name,
                        }
                    },
                    "Function": agg_func,
                }
            }
            where = []
            if min_val:
                where.append({"Condition": {"Comparison": {"ComparisonKind": 2, "Left": agg_expr, "Right": {"Literal": {"Value": _format_literal(min_val)}}}}})
            if max_val:
                where.append({"Condition": {"Comparison": {"ComparisonKind": 4, "Left": agg_expr, "Right": {"Literal": {"Value": _format_literal(max_val)}}}}})
            if not where:
                return None
            filter_type = "Advanced"
            field_ref = agg_field_ref
        else:
            # Row-level filter: use raw Column expression + Range type
            if min_val and max_val:
                where = [{"Condition": {"Between": {"Expression": col_expr, "LowerBound": {"Literal": {"Value": _format_literal(min_val)}}, "UpperBound": {"Literal": {"Value": _format_literal(max_val)}}}}}]
            elif min_val:
                where = [{"Condition": {"Comparison": {"ComparisonKind": 2, "Left": col_expr, "Right": {"Literal": {"Value": _format_literal(min_val)}}}}}]
            elif max_val:
                where = [{"Condition": {"Comparison": {"ComparisonKind": 4, "Left": col_expr, "Right": {"Literal": {"Value": _format_literal(max_val)}}}}}]
            else:
                return None
            filter_type = "Range"
    else:
        return None

    return {
        "name": filter_id,
        "field": field_ref,
        "type": filter_type,
        "filter": {
            "Version": 2,
            "From": from_clause,
            "Where": where,
        },
        "howCreated": "User",
        "isHiddenInViewMode": False,
    }


def _build_filter_config(filters: list[dict]) -> dict | None:
    """Build a PBI filterConfig dict from a list of enriched filter dicts."""
    entries = [e for i, f in enumerate(filters) for e in [_build_filter_entry(f, i)] if e]
    return {"filters": entries} if entries else None


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
    database_tmdl = f"database '{name}'\n\tcompatibilityLevel: 1600\n"
    (defn_dir / "database.tmdl").write_text(database_tmdl, encoding="utf-8")

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
    (defn_dir / "model.tmdl").write_text(model_tmdl, encoding="utf-8")

    # Write relationships as a standalone file (PBI Desktop format)
    rels = transformed.get("relationships", [])
    rel_path = defn_dir / "relationships.tmdl"
    if rels:
        rel_lines = []
        for r in rels:
            rel_name = f"{r['from_table']}_{r['from_column']} -> {r['to_table']}_{r['to_column']}"
            rel_lines += [
                f"relationship '{rel_name}'",
                f"\tfromColumn: {r['from_table']}.{r['from_column']}",
                f"\ttoColumn: {r['to_table']}.{r['to_column']}",
                "",
            ]
        rel_path.write_text("\n".join(rel_lines), encoding="utf-8")
    elif rel_path.exists():
        rel_path.unlink()

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
    expr_lines = _build_m_expression(conn, data_dir, table["columns"])
    lines.append(f"\tpartition {qname} = m")
    lines.append(f"\t\tmode: {storage_mode}")
    lines.append("\t\tsource =")
    for line in expr_lines:
        lines.append(f"\t\t\t{line}")
    lines.append("")

    safe_name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    (tables_dir / f"{safe_name}.tmdl").write_text("\n".join(lines), encoding="utf-8")


def _build_m_expression(conn: dict, data_dir: Path, columns: list[dict] | None = None) -> list[str]:
    """Build Power Query M expression lines from connection info.

    For file-based sources (Excel, CSV), appends an explicit Table.TransformColumnTypes
    step derived from Tableau column metadata so PBI doesn't mistype numeric columns.
    """
    conn_type = conn.get("type", "")

    def _type_step(prev: str) -> list[str]:
        """Return lines for Table.TransformColumnTypes, or empty list if no columns."""
        if not columns:
            return []
        pairs = [
            f'        {{"{col["name"].replace(chr(34), chr(34)*2)}", {_M_TYPE_MAP[col["dataType"]]}}}'
            for col in columns
            if col["dataType"] in _M_TYPE_MAP
        ]
        if not pairs:
            return []
        return [
            f'    #"Changed Types" = Table.TransformColumnTypes({prev}, {{',
            *[p + "," for p in pairs[:-1]],
            pairs[-1],
            "    })",
        ]

    stem = Path(conn.get("filename", "")).stem
    xlsx = data_dir / f"{stem}.xlsx"
    xls = data_dir / f"{stem}.xls"
    resolved = xlsx if xlsx.exists() else xls
    filename = resolved.resolve().as_posix()
    table_name = conn.get("table_name", "")
    safe_var = table_name.replace(" ", "_").replace("-", "_")
    escaped_table = table_name.replace('"', '""')

    if conn_type == "excel-direct":
        type_lines = _type_step('#"Promoted Headers"')
        last_step = '#"Changed Types"' if type_lines else '#"Promoted Headers"'
        return [
            "let",
            f'    Source = Excel.Workbook(File.Contents("{filename}"), null, true),',
            f'    {safe_var}_Sheet = Source{{[Item="{escaped_table}",Kind="Sheet"]}}[Data],',
            f'    #"Promoted Headers" = Table.PromoteHeaders({safe_var}_Sheet, [PromoteAllScalars=true])'
            + ("," if type_lines else ""),
            *type_lines,
            "in",
            f"    {last_step}",
        ]

    if conn_type == "textscan":
        csv_path = (data_dir / conn.get("filename", "")).resolve().as_posix()
        type_lines = _type_step('#"Promoted Headers"')
        last_step = '#"Changed Types"' if type_lines else '#"Promoted Headers"'
        return [
            "let",
            f'    Source = Csv.Document(File.Contents("{csv_path}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.None]),',
            f'    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true])'
            + ("," if type_lines else ""),
            *type_lines,
            "in",
            f"    {last_step}",
        ]

    # SQL-based connections share the same structure; only the M connector function differs
    _SQL_CONNECTOR = {
        "postgres":  "PostgreSQL.Database",
        "sqlserver": "Sql.Database",
        "mysql":     "MySQL.Database",
        "redshift":  "AmazonRedshift.Database",
        "snowflake": "Snowflake.Databases",
        "oracle":    "Oracle.Database",
        "bigquery":  "GoogleBigQuery.Database",
    }

    if conn_type in _SQL_CONNECTOR:
        fn = _SQL_CONNECTOR[conn_type]
        server = conn.get("server", "")
        dbname = conn.get("dbname", "")
        custom_sql = conn.get("custom_sql", "")
        if custom_sql:
            escaped_sql = custom_sql.replace('"', '""')
            return [
                "let",
                f'    Source = {fn}("{server}", "{dbname}"),',
                f'    nav = Value.NativeQuery(Source, "{escaped_sql}", null, [EnableFolding=true])',
                "in",
                "    nav",
            ]
        schema = conn.get("schema", "")
        table = conn.get("table", "")
        return [
            "let",
            f'    Source = {fn}("{server}", "{dbname}"),',
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


def _write_report_json(definition_dir: Path, datasource_filters: list[dict] | None = None) -> None:
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
    if datasource_filters:
        filter_config = _build_filter_config(datasource_filters)
        if filter_config:
            content["filterConfig"] = filter_config
    (definition_dir / "report.json").write_text(json.dumps(content, indent=2))


def _write_pages(definition_dir: Path, transformed: dict) -> None:
    """Write one page folder per sheet under definition/pages/, plus pages.json manifest."""
    pages_dir = definition_dir / "pages"
    pages_dir.mkdir(exist_ok=True)

    # Group visuals by page_name (sheet), preserving insertion order
    pages: dict[str, list[dict]] = {}
    for v in transformed.get("visuals", []):
        key = v.get("page_name", v["name"])
        pages.setdefault(key, []).append(v)

    section_ids = []
    global_visual_idx = 0
    for i, (_, page_visuals) in enumerate(pages.items()):
        section_id = f"ReportSection{i + 1}"
        section_ids.append(section_id)
        page_dir = pages_dir / section_id
        page_dir.mkdir(exist_ok=True)
        _write_page(page_dir, page_visuals, global_visual_idx)
        global_visual_idx += len(page_visuals)

    _write_pages_manifest(pages_dir, section_ids)


def _write_pages_manifest(pages_dir: Path, section_ids: list[str]) -> None:
    """Write definition/pages/pages.json required by PBI Desktop for page discovery."""
    content = {
        "$schema": f"{_SCHEMA_BASE}/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": section_ids,
        "activePageName": section_ids[0] if section_ids else "",
    }
    (pages_dir / "pages.json").write_text(json.dumps(content, indent=2))


def _write_page(page_dir: Path, page_visuals: list[dict], base_visual_idx: int) -> None:
    """Write page.json and visuals for this sheet. Multiple visuals are laid out side-by-side."""
    display_name = page_visuals[0].get("page_name", page_visuals[0]["name"])
    page = {
        "$schema": f"{_SCHEMA_BASE}/definition/page/2.1.0/schema.json",
        "name": page_dir.name,
        "displayName": display_name,
        "displayOption": "FitToPage",
        "height": 720,
        "width": 1280,
    }
    (page_dir / "page.json").write_text(json.dumps(page, indent=2))

    slot = 0
    for j, visual_info in enumerate(page_visuals):
        if visual_info.get("row_fields") or visual_info.get("col_fields"):
            visuals_dir = page_dir / "visuals"
            visuals_dir.mkdir(exist_ok=True)
            visual_dir = visuals_dir / f"visual_{base_visual_idx + j + 1}"
            visual_dir.mkdir(exist_ok=True)
            _write_visual(visual_dir, visual_info, x_offset=20 + slot * 620)
            slot += 1


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


def _build_sort_definition(sorts: list[dict]) -> dict | None:
    """Build PBI sortDefinition from enriched sort list. Returns None if no sorts."""
    if not sorts:
        return None
    items = []
    for s in sorts:
        expr_key = "Measure" if s["is_measure"] else "Column"
        items.append({
            "field": {
                expr_key: {
                    "Expression": {"SourceRef": {"Entity": s["sort_table"]}},
                    "Property": s["sort_field"],
                }
            },
            "direction": "Ascending" if s["direction"] == "ASC" else "Descending",
        })
    return {"sort": items, "isDefaultSort": False}


def _write_visual(visual_dir: Path, visual_info: dict, x_offset: int = 20) -> None:
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

    query: dict = {"queryState": query_state}
    sort_def = _build_sort_definition(visual_info.get("sorts", []))
    if sort_def:
        query["sortDefinition"] = sort_def

    visual_obj: dict = {"visualType": visual_type, "query": query}
    if visual_info.get("show_data_labels") and visual_type != "tableEx":
        visual_obj["objects"] = {
            "labels": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}]
        }
    title_info = visual_info.get("title")
    if title_info:
        visual_obj["visualContainerObjects"] = _build_title_objects(title_info)
    container: dict = {
        "$schema": f"{_SCHEMA_BASE}/definition/visualContainer/1.0.0/schema.json",
        "name": visual_dir.name,
        "position": {"x": x_offset, "y": 20, "z": 0, "height": 360, "width": 560, "tabOrder": 0},
        "visual": visual_obj,
    }

    filter_config = _build_filter_config(visual_info.get("filters", []))
    if filter_config:
        container["filterConfig"] = filter_config

    (visual_dir / "visual.json").write_text(json.dumps(container, indent=2))


def _build_title_objects(title_info: dict) -> dict:
    """Build the visualContainerObjects.title block from a parsed title dict."""
    def lit(value: str) -> dict:
        return {"expr": {"Literal": {"Value": value}}}

    props: dict = {
        "show": lit("true"),
        "text": lit(f"'{title_info['text']}'"),
    }
    if "font_size" in title_info:
        props["fontSize"] = lit(str(title_info["font_size"]))
    if "font_family" in title_info:
        props["fontFamily"] = lit(f"'{title_info['font_family']}'")
    if "font_color" in title_info:
        props["fontColor"] = lit(f"'{title_info['font_color']}'")
    if "bold" in title_info:
        props["bold"] = lit("true")
    if "italic" in title_info:
        props["italic"] = lit("true")
    if "underline" in title_info:
        props["underline"] = lit("true")

    return {"title": [{"properties": props}]}
