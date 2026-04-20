"""Transform parsed workbook dict into PBIR-ready structure."""

DATATYPE_MAP = {
    "string": "string",
    "integer": "int64",
    "real": "double",
    "date": "dateTime",
    "datetime": "dateTime",
    "boolean": "boolean",
}

_AGG_LABEL = {
    "DISTINCTCOUNT": "Count Distinct",
    "COUNTA": "Count",
    "SUM": "Sum",
    "AVERAGE": "Avg",
    "MIN": "Min",
    "MAX": "Max",
    "MEDIAN": "Median",
}


def transform(workbook: dict) -> dict:
    """Return transformed dict with tables, measures, visuals, relationships, and report."""
    tables = []
    relationships = []
    # field_lookup: ds_name → {field_name: pbi_table_name}
    field_lookup: dict[str, dict[str, str]] = {}
    pending_calc_fields: list[dict] = []

    # calc_name_lookup: ds_name → {internal_name: display_name}
    calc_name_lookup: dict[str, dict[str, str]] = {}

    for ds in workbook.get("datasources", []):
        ds_tables, ds_rels, ds_fields = _map_datasource(ds)
        tables.extend(ds_tables)
        relationships.extend(ds_rels)
        field_lookup[ds["name"]] = ds_fields
        calc_name_lookup[ds["name"]] = ds.get("calc_name_map", {})
        primary_table = ds_tables[0]["name"] if ds_tables else ""
        for cf in ds.get("calculated_fields", []):
            pending_calc_fields.append({
                "name": cf["name"],
                "internal_name": cf["internal_name"],
                "formula": cf["formula"],
                "datatype": cf["datatype"],
                "role": cf["role"],
                "table": primary_table,
                "status": "pending_translation",
            })

    measures: dict[tuple, dict] = {}
    visuals = _process_sheets(workbook, tables, field_lookup, calc_name_lookup, measures)

    sheet_filters = [
        {"sheet": s["name"], "filters": s.get("filters", [])}
        for s in workbook.get("sheets", [])
        if s.get("filters")
    ]
    report = {
        "calculated_fields": pending_calc_fields,
        "unsupported": workbook.get("unsupported", []),
        "tables_generated": [t["name"] for t in tables],
        "sheet_filters": sheet_filters,
    }

    return {
        **workbook,
        "tables": tables,
        "visuals": visuals,
        "measures": list(measures.values()),
        "relationships": relationships,
        "report": report,
    }


def _map_datasource(ds: dict) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Map a parsed datasource to PBI tables, relationships, and field→table lookup.

    Returns (tables, relationships, field_table_map).
    """
    conn = ds["connection"]
    conn_type = conn.get("type", "")
    ds_tables_meta = ds.get("tables", [])
    columns = ds.get("columns", [])

    if conn_type == "postgres" and len(ds_tables_meta) > 1:
        return _map_multi_table_postgres(ds, columns, conn, ds_tables_meta)

    # Single-table path (excel, csv, etc.)
    pbi_table_name = ds["caption"]
    pbi_columns = [
        {
            "name": col["name"],
            "dataType": DATATYPE_MAP.get(col["datatype"], "string"),
            "sourceColumn": col["name"],
        }
        for col in columns
    ]
    table = {"name": pbi_table_name, "connection": conn, "columns": pbi_columns}
    field_map = {col["name"]: pbi_table_name for col in columns}
    return [table], [], field_map


def _map_multi_table_postgres(
    ds: dict,
    columns: list[dict],
    conn: dict,
    tables_meta: list[dict],
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Map a multi-table postgres datasource to separate PBI tables."""
    # Group columns by source_table
    by_table: dict[str, list[dict]] = {t["name"]: [] for t in tables_meta}
    field_map: dict[str, str] = {}

    for col in columns:
        src = col.get("source_table", "")
        if src in by_table:
            by_table[src].append({
                "name": col["name"],
                "dataType": DATATYPE_MAP.get(col["datatype"], "string"),
                "sourceColumn": col["name"],
            })
            field_map[col["name"]] = src

    pbi_tables = []
    for t in tables_meta:
        tname = t["name"]
        table_conn = {**conn, "schema": t["schema"], "table": t["table"], "table_name": tname}
        pbi_tables.append({
            "name": tname,
            "connection": table_conn,
            "columns": by_table.get(tname, []),
        })

    relationships = [
        {
            "from_table": r["from_table"],
            "from_column": r["from_column"],
            "to_table": r["to_table"],
            "to_column": r["to_column"],
        }
        for r in ds.get("relationships", [])
    ]

    return pbi_tables, relationships, field_map


def _process_sheets(
    workbook: dict,
    tables: list[dict],
    field_lookup: dict[str, dict[str, str]],
    calc_name_lookup: dict[str, dict[str, str]],
    measures: dict,
) -> list[dict]:
    """Map sheets to visual descriptors, generating DAX measures for aggregated fields."""
    ds_list = workbook.get("datasources", [])
    ds_default_table = {ds["name"]: tables[i]["name"] for i, ds in enumerate(ds_list) if i < len(tables)}

    visuals = []
    for sheet in workbook.get("sheets", []):
        ds_name = sheet["datasource"]
        fmap = field_lookup.get(ds_name, {})
        cmap = calc_name_lookup.get(ds_name, {})
        default_table = ds_default_table.get(ds_name, "")

        rows, cols = sheet["rows"], sheet["cols"]
        mark_type = sheet["mark_type"]
        if mark_type == "Automatic":
            mark_type = _infer_mark_type(rows, cols)

        row_fields = [r for f in rows for r in [_resolve_field(f, fmap, cmap, default_table, measures)] if r]
        col_fields = [r for f in cols for r in [_resolve_field(f, fmap, cmap, default_table, measures)] if r]

        visuals.append({
            "name": sheet["name"],
            "table": default_table,
            "field_table_map": fmap,
            "row_fields": row_fields,
            "col_fields": col_fields,
            "mark_type": mark_type,
            "filters": sheet.get("filters", []),
        })
    return visuals


def _resolve_field(
    field: dict | str,
    field_table_map: dict[str, str],
    calc_name_map: dict[str, str],
    default_table: str,
    measures: dict,
) -> dict | None:
    """Return {name, is_measure, table} ref, or None if field is a pending calc field."""
    if not isinstance(field, dict):
        if field in calc_name_map:
            return None  # calculated field pending translation — skip projection
        tname = field_table_map.get(field, default_table)
        return {"name": field, "is_measure": False, "table": tname}

    agg = field.get("aggregation")
    name = field["name"]

    if name in calc_name_map:
        return None  # calculated field pending translation — skip projection

    tname = field_table_map.get(name, default_table)

    if not agg or not tname:
        return {"name": name, "is_measure": False, "table": tname or default_table}

    label = _AGG_LABEL.get(agg, agg)
    measure_name = f"{label} {name}"
    key = (tname, measure_name)
    if key not in measures:
        tname_q = f"'{tname}'" if any(c in tname for c in " ()/-.,") else tname
        measures[key] = {
            "name": measure_name,
            "table": tname,
            "dax": f"{agg}({tname_q}[{name}])",
        }
    return {"name": measure_name, "is_measure": True, "table": tname}


def _infer_mark_type(rows: list, cols: list) -> str:
    """Infer chart type from shelf layout when Tableau mark is Automatic."""
    rows_cont = any(f.get("continuous") for f in rows if isinstance(f, dict))
    cols_cont = any(f.get("continuous") for f in cols if isinstance(f, dict))

    if cols_cont and not rows_cont:
        return "Bar"
    if rows_cont and not cols_cont:
        return "Column"
    if cols_cont and rows_cont:
        return "Line"
    return "Automatic"
