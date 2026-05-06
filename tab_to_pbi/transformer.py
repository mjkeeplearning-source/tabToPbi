"""Transform parsed workbook dict into PBIR-ready structure."""

import re

_SQL_CONN_TYPES = {"postgres", "sqlserver", "mysql", "bigquery", "redshift", "snowflake", "oracle"}

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
    "VAR.S": "Var",
    "VAR.P": "VarP",
    "STDEV.S": "StDev",
    "STDEV.P": "StDevP",
}


def _best_table_for_calc(formula: str, field_map: dict[str, str], primary_table: str) -> str:
    """Return the table that owns the most column references in a Tableau formula.

    Extracts [ColumnName] tokens, looks each up in field_map, and picks the table
    with the highest hit count. Tiebreak: first referenced column wins. Falls back
    to primary_table when no columns resolve.
    """
    refs = re.findall(r'\[([^\]]+)\]', formula)
    counts: dict[str, int] = {}
    for ref in refs:
        t = field_map.get(ref)
        if t:
            counts[t] = counts.get(t, 0) + 1
    if not counts:
        return primary_table
    max_count = max(counts.values())
    for ref in refs:
        t = field_map.get(ref)
        if t and counts[t] == max_count:
            return t
    return primary_table


def _apply_storage_mode(conn: dict) -> dict:
    """Return conn with storage_mode set based on live_connection flag."""
    if conn.get("live_connection"):
        return {**conn, "storage_mode": "directQuery"}
    return {**conn, "storage_mode": "import"}


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
            best_table = _best_table_for_calc(cf["formula"], ds_fields, primary_table)
            pending_calc_fields.append({
                "name": cf["name"],
                "internal_name": cf["internal_name"],
                "formula": cf["formula"],
                "datatype": cf["datatype"],
                "role": cf["role"],
                "table": best_table,
                "status": "pending_translation",
            })

    # Build display_name → table map so visual field refs stay in sync with TMDL host table
    calc_table_map: dict[str, str] = {cf["name"]: cf["table"] for cf in pending_calc_fields}

    measures: dict[tuple, dict] = {}
    visuals, visual_warnings = _process_sheets(workbook, tables, field_lookup, calc_name_lookup, measures, calc_table_map)

    sheet_filters = [
        {"sheet": s["name"], "filters": s.get("filters", [])}
        for s in workbook.get("sheets", [])
        if s.get("filters")
    ]
    relationship_warnings = [
        (
            f"Relationship {r['from_table']}.{r['from_column']} -> "
            f"{r['to_table']}.{r['to_column']} "
            f"({r['from_cardinality']}:{r['to_cardinality']}, method={r['cardinality_method']}): "
            "cardinality inferred — verify in PBI Desktop Model View after opening"
        )
        for r in relationships
        if "from_cardinality" in r
    ]
    report = {
        "calculated_fields": pending_calc_fields,
        "unsupported": workbook.get("unsupported", []) + visual_warnings,
        "tables_generated": [t["name"] for t in tables],
        "sheet_filters": sheet_filters,
        "relationship_cardinality_warnings": relationship_warnings,
    }

    # Merge all datasource calc_name_maps into one for the translator
    merged_calc_name_map: dict[str, str] = {}
    for ds in workbook.get("datasources", []):
        merged_calc_name_map.update(ds.get("calc_name_map", {}))

    # Enrich datasource_filters with table names for report-level filter generation
    all_field_map: dict[str, str] = {}
    for fmap in field_lookup.values():
        all_field_map.update(fmap)
    default_table_name = tables[0]["name"] if tables else ""
    datasource_filters = [
        {**f, "table": all_field_map.get(f["field"], default_table_name)}
        for f in workbook.get("datasource_filters", [])
    ]

    return {
        **workbook,
        "tables": tables,
        "visuals": visuals,
        "measures": list(measures.values()),
        "relationships": relationships,
        "report": report,
        "calc_name_map": merged_calc_name_map,
        "datasource_filters": datasource_filters,
    }


def _col_matches_table(col: str, table: str) -> bool:
    """True if col is likely the PK of table: strip suffix, singularize, exact match.

    e.g. CustomerID / Customers → True; CustomerID / Orders → False.
    """
    base = re.sub(r"(ID|Id|Key|Code|No)$", "", col).lower().rstrip("s")
    tname = table.lower().rstrip("s")
    return bool(base) and base == tname


def _infer_cardinality(
    join_type: str, from_table: str, from_col: str, to_table: str, to_col: str
) -> tuple[str, str, str]:
    """Return (from_cardinality, to_cardinality, method) using Signal 2 + Signal 1 + fallback.

    Convention matches parser output:
      from_table = LEFT clause expression table (accumulated / preserved side for LEFT JOIN)
      to_table   = RIGHT clause expression table (new RIGHT-child table)

    Signal 2 — structural (LEFT JOIN definitive; INNER JOIN primary):
      LEFT  JOIN: from_table (preserved LEFT child) = one side — no override.
      INNER JOIN: from_table (accumulated LEFT expression) = one side — Signal 1 can override.

    Signal 1 — naming convention (FULL OUTER primary; INNER confirmation/override):
      Strip PK suffix, singularize, exact-match col base against table name.
      Whichever side matches owns the PK = one side.

    Fallback: to_table = one (RIGHT child = new/added table = typically dimension/lookup).
    Always produces one:many or many:one — never one:one or many:many.
    """
    from_is_pk = _col_matches_table(from_col, from_table)
    to_is_pk = _col_matches_table(to_col, to_table)

    if join_type == "left":
        # Signal 2 definitive: LEFT child (from_table) is preserved = one side.
        return ("one", "many", "signal2_left")

    if join_type == "inner":
        # Signal 2 extended primary: from_table (accumulated LEFT expression) = one side.
        # Signal 1 overrides when naming convention contradicts Signal 2.
        if to_is_pk and not from_is_pk:
            return ("many", "one", "signal1_override_inner")
        if from_is_pk and not to_is_pk:
            return ("one", "many", "signal2_confirmed_signal1_inner")
        # Signal 1 silent or ambiguous — Signal 2 default stands.
        return ("one", "many", "signal2_inner")

    # FULL OUTER JOIN — Signal 2 unreliable; Signal 1 primary.
    if from_is_pk and not to_is_pk:
        return ("one", "many", "signal1_full")
    if to_is_pk and not from_is_pk:
        return ("many", "one", "signal1_full")
    # Fallback: to_table (RIGHT child, new/added table) = one (dimension convention).
    return ("many", "one", "fallback")


def _map_relationship(r: dict) -> dict:
    """Convert a parsed relationship to a PBI relationship dict with cardinality.

    Logical relationships (no join_type) get no explicit cardinality — PBI defaults (many:one) apply.
    Physical joins get cardinality inferred from join type + naming signals.
    """
    if "join_type" not in r:
        return {
            "from_table": r["from_table"],
            "from_column": r["from_column"],
            "to_table": r["to_table"],
            "to_column": r["to_column"],
        }
    from_card, to_card, method = _infer_cardinality(
        r["join_type"], r["from_table"], r["from_column"], r["to_table"], r["to_column"]
    )
    return {
        "from_table": r["from_table"],
        "from_column": r["from_column"],
        "to_table": r["to_table"],
        "to_column": r["to_column"],
        "from_cardinality": from_card,
        "to_cardinality": to_card,
        "cardinality_method": method,
    }


def _map_datasource(ds: dict) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Map a parsed datasource to PBI tables, relationships, and field→table lookup.

    Returns (tables, relationships, field_table_map).
    """
    conn = ds["connection"]
    conn_type = conn.get("type", "")
    ds_tables_meta = ds.get("tables", [])
    columns = ds.get("columns", [])

    if conn_type in _SQL_CONN_TYPES and len(ds_tables_meta) > 1:
        return _map_multi_table_sql(ds, columns, conn, ds_tables_meta)

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
    effective_conn = _apply_storage_mode(conn)
    table = {"name": pbi_table_name, "connection": effective_conn, "columns": pbi_columns}
    field_map = {col["name"]: pbi_table_name for col in columns}
    return [table], [], field_map


def _map_multi_table_sql(
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
            physical = col.get("remote_name", col["name"])
            by_table[src].append({
                "name": physical,
                "dataType": DATATYPE_MAP.get(col["datatype"], "string"),
                "sourceColumn": physical,
            })
            # map both logical name and physical name to the source table
            field_map[col["name"]] = src
            field_map[physical] = src

    pbi_tables = []
    for t in tables_meta:
        tname = t["name"]
        table_conn = _apply_storage_mode({**conn, "schema": t["schema"], "table": t["table"], "table_name": tname})
        pbi_tables.append({
            "name": tname,
            "connection": table_conn,
            "columns": by_table.get(tname, []),
        })

    relationships = [
        _map_relationship(r)
        for r in ds.get("relationships", [])
    ]

    return pbi_tables, relationships, field_map


_SUPPORTED_MARK_TYPES = {
    "Bar", "Column", "Line", "Area", "Pie",
    "Circle", "Shape", "Polygon", "Multipolygon", "PolyLine",
    "Text", "Automatic",
}


def _process_sheets(
    workbook: dict,
    tables: list[dict],
    field_lookup: dict[str, dict[str, str]],
    calc_name_lookup: dict[str, dict[str, str]],
    measures: dict,
    calc_table_map: dict[str, str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Map sheets to visual descriptors. Returns (visuals, unsupported_warnings)."""
    ds_list = workbook.get("datasources", [])
    ds_default_table = {ds["name"]: tables[i]["name"] for i, ds in enumerate(ds_list) if i < len(tables)}
    # column_formats: ds_name → {col_name: format_string}
    ds_col_formats = {ds["name"]: ds.get("column_formats", {}) for ds in ds_list}

    visuals = []
    unsupported_warnings: list[str] = []
    for sheet in workbook.get("sheets", []):
        ds_name = sheet["datasource"]
        fmap = field_lookup.get(ds_name, {})
        cmap = calc_name_lookup.get(ds_name, {})
        col_formats = ds_col_formats.get(ds_name, {})
        default_table = ds_default_table.get(ds_name, "")

        rows, cols = sheet["rows"], sheet["cols"]
        mark_type = sheet["mark_type"]
        mark_orientation = sheet.get("mark_orientation", "")
        if mark_type == "Automatic":
            mark_type = _infer_mark_type(rows, cols)
        elif mark_type == "Bar" and mark_orientation == "y":
            mark_type = "Column"

        if mark_type not in _SUPPORTED_MARK_TYPES:
            unsupported_warnings.append(
                f"Sheet '{sheet['name']}': mark type '{mark_type}' not supported — rendered as table"
            )

        row_fields = [r for f in rows for r in [_resolve_field(f, fmap, cmap, default_table, measures, calc_table_map)] if r]
        col_fields = [r for f in cols for r in [_resolve_field(f, fmap, cmap, default_table, measures, calc_table_map)] if r]

        # Bar mark with measure on rows shelf = vertical bars → columnChart in PBI
        if mark_type == "Bar" and any(f.get("is_measure") for f in row_fields):
            mark_type = "Column"

        # Resolve color encoding fields (heatmap intensity) and append to col_fields as measures only
        enc_raw = sheet.get("encoding_fields", [])
        enc_resolved = [
            r for f in enc_raw
            for r in [_resolve_field(f, fmap, cmap, default_table, measures, calc_table_map)]
            if r and r.get("is_measure")
        ]
        if enc_resolved:
            if mark_type == "Automatic":
                unsupported_warnings.append(
                    f"Sheet '{sheet['name']}': heatmap color encoding has no PBI equivalent — color measure added as table column"
                )
            col_fields = col_fields + enc_resolved

        col_measures = [f for f in col_fields if f and f.get("is_measure")]
        col_dims = [f for f in col_fields if f and not f.get("is_measure")]

        # Enrich filters with table names for PBI filter generation
        enriched_filters = [
            {**f, "table": fmap.get(f["field"], default_table)}
            for f in sheet.get("filters", [])
        ]

        enriched_sorts, sort_warnings = _enrich_sorts(sheet.get("sorts", []), fmap, cmap, default_table)
        unsupported_warnings.extend(sort_warnings)

        # Collect unsupported format elements for migration report
        visual_fmt = sheet.get("visual_format", {})
        for elem in visual_fmt.get("unsupported_elements", []):
            unsupported_warnings.append(
                f"Sheet '{sheet['name']}': Tableau style-rule element '{elem}' has no PBI equivalent — skipped"
            )

        show_data_labels = sheet.get("show_data_labels", False)
        sheet_title = sheet.get("title")
        if len(col_measures) > 1:
            # Multiple measures on cols shelf → one visual per measure on the same page
            for m in col_measures:
                visuals.append({
                    "name": f"{sheet['name']} - {m['name']}",
                    "page_name": sheet["name"],
                    "title": sheet_title,
                    "table": default_table,
                    "field_table_map": fmap,
                    "row_fields": row_fields,
                    "col_fields": col_dims + [m],
                    "mark_type": mark_type,
                    "show_data_labels": show_data_labels,
                    "filters": enriched_filters,
                    "sorts": enriched_sorts,
                    "visual_format": visual_fmt,
                    "col_formats": col_formats,
                })
        else:
            visuals.append({
                "name": sheet["name"],
                "page_name": sheet["name"],
                "title": sheet_title,
                "table": default_table,
                "field_table_map": fmap,
                "row_fields": row_fields,
                "col_fields": col_fields,
                "mark_type": mark_type,
                "show_data_labels": show_data_labels,
                "filters": enriched_filters,
                "sorts": enriched_sorts,
                "visual_format": visual_fmt,
                "col_formats": col_formats,
            })
    return visuals, unsupported_warnings


def _enrich_sorts(
    sorts: list[dict],
    fmap: dict[str, str],
    cmap: dict[str, str],
    default_table: str,
) -> tuple[list[dict], list[str]]:
    """Enrich parsed sorts with table names and resolved field names for PBI sortDefinition.

    Returns (enriched_sorts, warnings). Manual sorts are skipped (unsupported in PBI).
    For computed-sorts the using field (the measure driving the sort) becomes sort_field.
    For natural/alphabetic sorts the column itself becomes sort_field.
    """
    enriched: list[dict] = []
    warnings: list[str] = []
    for s in sorts:
        sort_type = s["type"]
        direction = s["direction"]
        field = s["field"]

        if sort_type == "manual":
            warnings.append(f"Manual sort on '{field}' is not supported in PBI — skipped")
            continue

        if sort_type == "computed":
            using = s.get("using", "")
            using_prefix = s.get("using_prefix", "")
            if using_prefix == "usr":
                # User-defined calc field: resolve internal name → display name
                if using not in cmap:
                    warnings.append(
                        f"Computed sort on '{field}' references unknown calc field '{using}' — skipped"
                    )
                    continue
                sort_field = cmap[using]
                sort_table = fmap.get(sort_field, default_table)
                is_measure = True
            elif using_prefix in _AGG_LABEL:
                # Regular aggregated column auto-measure: e.g. sum:profit → "Sum profit"
                sort_field = f"{_AGG_LABEL[using_prefix]} {using}"
                sort_table = fmap.get(using, default_table)
                is_measure = True
            elif using:
                sort_field = using
                sort_table = fmap.get(using, default_table)
                is_measure = True
            else:
                warnings.append(f"Computed sort on '{field}': missing using field — skipped")
                continue
            enriched.append({
                "sort_field": sort_field,
                "sort_table": sort_table,
                "direction": direction,
                "is_measure": is_measure,
            })
        else:
            # natural-sort or alphabetic-sort: sort by the column itself
            table = fmap.get(field, default_table)
            enriched.append({
                "sort_field": field,
                "sort_table": table,
                "direction": direction,
                "is_measure": False,
            })
    return enriched, warnings


def _resolve_field(
    field: dict | str,
    field_table_map: dict[str, str],
    calc_name_map: dict[str, str],
    default_table: str,
    measures: dict,
    calc_table_map: dict[str, str] | None = None,
) -> dict | None:
    """Return {name, is_measure, table} ref, or None if field is a pending calc field."""
    ctmap = calc_table_map or {}
    if not isinstance(field, dict):
        if field in calc_name_map:
            display_name = calc_name_map[field]
            return {"name": display_name, "is_measure": True, "table": ctmap.get(display_name, default_table)}
        tname = field_table_map.get(field, default_table)
        return {"name": field, "is_measure": False, "table": tname}

    agg = field.get("aggregation")
    name = field["name"]

    if name in calc_name_map:
        display_name = calc_name_map[name]
        return {"name": display_name, "is_measure": True, "table": ctmap.get(display_name, default_table)}

    tname = field_table_map.get(name, default_table)

    if field.get("date_part"):
        # Bind the raw date column; PBI's date hierarchy handles year/month/day granularity
        return {"name": name, "is_measure": False, "table": tname or default_table}

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
