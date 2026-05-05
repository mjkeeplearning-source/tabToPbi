"""Parse .twb / .twbx files into a workbook dict."""

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def parse(path: Path) -> dict:
    """Return a workbook dict from a .twb or .twbx file."""
    if path.suffix.lower() == ".twbx":
        root = _parse_twbx(path)
    else:
        root = ET.parse(path).getroot()

    datasources, join_flags = _parse_datasources(root)
    sheets = _parse_sheets(root)
    unsupported = _detect_unsupported(root, datasources) + join_flags

    return {
        "name": path.stem,
        "datasources": datasources,
        "sheets": sheets,
        "unsupported": unsupported,
        "datasource_filters": _parse_datasource_filters(root),
    }


def _parse_twbx(path: Path) -> ET.Element:
    """Unzip .twbx and return the root element of the embedded .twb."""
    with zipfile.ZipFile(path) as zf:
        twb_name = next(n for n in zf.namelist() if n.endswith(".twb"))
        with zf.open(twb_name) as f:
            return ET.parse(f).getroot()


def extract_twbx_data(path: Path, dest_dir: Path) -> Path:
    """Extract embedded data files from a .twbx into dest_dir (flat layout).

    Returns dest_dir. Only non-.twb entries are extracted; directory structure
    is flattened so each file lands directly in dest_dir.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.endswith(".twb") or name.endswith("/"):
                continue
            filename = Path(name).name
            dest = dest_dir / filename
            dest.write_bytes(zf.read(name))
    return dest_dir


def _parse_datasources(root: ET.Element) -> tuple[list[dict], list[str]]:
    """Extract datasource info. Returns (datasources, physical_join_flags)."""
    results = []
    all_join_flags: list[str] = []
    for ds in root.findall("./datasources/datasource"):
        name = ds.get("name", "")
        if name in ("Parameters",) or not name:
            continue

        connection = _parse_connection(ds)
        tables = _parse_tables(ds, connection)
        columns = _parse_columns(ds, connection)
        calculated_fields = _parse_calculated_fields(ds)
        logical_rels = _parse_relationships(ds)
        physical_rels, join_flags = _parse_physical_joins(ds.find("connection"))
        all_join_flags.extend(join_flags)
        relationships = logical_rels + physical_rels
        calc_name_map = {cf["internal_name"]: cf["name"] for cf in calculated_fields}

        results.append({
            "name": name,
            "caption": ds.get("caption", name),
            "connection": connection,
            "tables": tables,
            "columns": columns,
            "calculated_fields": calculated_fields,
            "calc_name_map": calc_name_map,
            "relationships": relationships,
        })
    return results, all_join_flags


def _parse_connection(ds: ET.Element) -> dict:
    """Extract connection details."""
    conn = ds.find("connection")
    if conn is None:
        return {}

    conn_class = conn.get("class", "")

    if conn_class == "federated":
        named = conn.find("./named-connections/named-connection/connection")
        if named is not None:
            actual_class = named.get("class", "")
            filename = named.get("filename", "")
            server = named.get("server", "")
            dbname = named.get("dbname", "")
            port = named.get("port", "")
            username = named.get("username", "")
        else:
            actual_class = filename = server = dbname = port = username = ""

        relation = conn.find("relation")
        rel_type = relation.get("type", "") if relation is not None else ""
        table = ""
        table_name = ""
        custom_sql = ""
        if relation is not None and rel_type == "text":
            custom_sql = (relation.text or "").strip()
            table_name = relation.get("name", "Custom SQL Query")
        elif relation is not None and rel_type not in ("collection", "join"):
            table = relation.get("table", "").strip("[]")
            table_name = relation.get("name", "")
    else:
        actual_class = conn_class
        filename = conn.get("filename", "")
        server = conn.get("server", "")
        dbname = conn.get("dbname", "")
        port = conn.get("port", "")
        username = conn.get("username", "")
        relation = conn.find("relation")
        custom_sql = ""
        if relation is not None and relation.get("type") == "text":
            custom_sql = (relation.text or "").strip()
            table = ""
            table_name = relation.get("name", "Custom SQL Query")
        else:
            table = relation.get("table", "").strip("[]") if relation is not None else ""
            table_name = relation.get("name", "") if relation is not None else ""

    extract_el = ds.find("extract")
    live_connection = actual_class in _SQL_CONN_TYPES and (
        extract_el is None or extract_el.get("enabled", "true") == "false"
    )

    return {
        "type": actual_class,
        "filename": filename,
        "server": server,
        "dbname": dbname,
        "port": port,
        "username": username,
        "table": table,
        "table_name": table_name,
        "custom_sql": custom_sql,
        "live_connection": live_connection,
    }


def _parse_tables(ds: ET.Element, connection: dict) -> list[dict]:
    """Extract physical table list. For collection relations returns all child tables."""
    conn = ds.find("connection")
    if conn is None:
        return []

    relation = conn.find("relation")
    if relation is None:
        return []

    if relation.get("type") == "collection":
        tables = []
        for child in relation.findall("relation[@type='table']"):
            raw_table = child.get("table", "")  # e.g. [superstore].[orders]
            parts = raw_table.strip("[]").split("].[")
            schema = parts[0] if len(parts) == 2 else ""
            table = parts[1] if len(parts) == 2 else raw_table.strip("[]")
            tables.append({
                "name": child.get("name", table),
                "schema": schema,
                "table": table,
            })
        return tables

    if relation.get("type") == "join":
        tables = []
        for r in relation.iter("relation"):
            if r.get("type") == "table":
                raw_table = r.get("table", "")
                parts = raw_table.strip("[]").split("].[")
                schema = parts[0] if len(parts) == 2 else ""
                table_name = parts[1] if len(parts) == 2 else raw_table.strip("[]")
                tables.append({
                    "name": r.get("name", table_name),
                    "schema": schema,
                    "table": table_name,
                })
        return tables

    # Single table
    table_name = connection.get("table_name") or connection.get("table", "")
    if table_name:
        return [{"name": table_name, "schema": "", "table": table_name}]
    return []


def _parse_columns(ds: ET.Element, connection: dict) -> list[dict]:
    """Extract columns with source_table info.

    For collection (multi-table): uses metadata-records (has parent-name) and
    cols/map to build source_table assignment.
    For single-table: uses relation/columns/column elements.
    """
    conn = ds.find("connection")
    if conn is None:
        return []

    relation = conn.find("relation")
    if relation is not None and relation.get("type") == "collection":
        # Build logical-name → source_table and → physical column from cols/map
        col_table: dict[str, str] = {}
        col_physical: dict[str, str] = {}
        for m in conn.findall("./cols/map"):
            key = m.get("key", "").strip("[]")     # e.g. "order_id (returns)"
            value = m.get("value", "")              # e.g. "[returns].[order_id]"
            parts = value.strip("[]").split("].[")
            if len(parts) == 2:
                col_table[key] = parts[0]           # "returns"
                col_physical[key] = parts[1]        # "order_id"

        # Build columns from metadata-records
        cols = []
        for mr in conn.findall("./metadata-records/metadata-record[@class='column']"):
            local_name = mr.findtext("local-name", "").strip("[]")
            local_type = mr.findtext("local-type", "string")
            parent_name = mr.findtext("parent-name", "").strip("[]")
            source_table = col_table.get(local_name, "") or parent_name
            remote_name = col_physical.get(local_name, local_name)
            if local_name:
                cols.append({
                    "name": local_name,
                    "remote_name": remote_name,
                    "datatype": local_type,
                    "source_table": source_table,
                })
        return cols

    # Single-table fallback
    cols = []
    for col in ds.findall("./connection/relation/columns/column"):
        cols.append({
            "name": col.get("name", ""),
            "datatype": col.get("datatype", ""),
            "source_table": connection.get("table_name", ""),
        })
    return cols


def _parse_calculated_fields(ds: ET.Element) -> list[dict]:
    """Extract calculated field definitions with name, formula, datatype, role, and internal_name."""
    fields = []
    for col in ds.findall("./column"):
        formula = col.find("calculation")
        if formula is not None:
            internal_name = col.get("name", "").strip("[]")
            fields.append({
                "name": col.get("caption", internal_name),
                "internal_name": internal_name,
                "formula": formula.get("formula", ""),
                "datatype": col.get("datatype", ""),
                "role": col.get("role", ""),
            })
    return fields


def _parse_physical_joins(conn: ET.Element) -> tuple[list[dict], list[str]]:
    """Extract relationships from physical-layer join relations.

    INNER + LEFT + RIGHT → PBI relationships (RIGHT is flipped to LEFT).
    FULL OUTER + non-equi → unsupported flags.
    Returns (relationships, unsupported_flags).
    """
    rels = []
    flags = []
    if conn is None:
        return rels, flags
    top_rel = conn.find("relation")
    if top_rel is None or top_rel.get("type") != "join":
        return rels, flags

    join_type = top_rel.get("join", "inner").lower().replace(" ", "")
    if join_type in ("full", "fullouter", "fullouterjoin"):
        child_names = [r.get("name", "") for r in top_rel.findall("relation")]
        flags.append(f"FULL OUTER join on {child_names} is not supported")
        return rels, flags

    exprs = top_rel.findall("./clause[@type='join']/expression[@op='=']/expression")
    if len(exprs) != 2:
        flags.append("Non-equi join detected — not supported")
        return rels, flags

    def _split(op: str) -> tuple[str, str]:
        parts = op.strip("[]").split("].[")
        return (parts[0], parts[1]) if len(parts) == 2 else ("", op)

    left_table, left_col = _split(exprs[0].get("op", ""))
    right_table, right_col = _split(exprs[1].get("op", ""))

    if join_type in ("right", "rightouter"):
        left_table, left_col, right_table, right_col = right_table, right_col, left_table, left_col

    rels.append({
        "from_table": left_table,
        "from_column": left_col,
        "to_table": right_table,
        "to_column": right_col,
    })
    return rels, flags


def _parse_relationships(ds: ET.Element) -> list[dict]:
    """Extract relationships from object-graph (Tableau logical layer)."""
    rels = []
    for rel in ds.findall("./object-graph/relationships/relationship"):
        expr = rel.find("expression[@op='=']")
        if expr is None:
            continue
        exprs = expr.findall("expression")
        if len(exprs) != 2:
            continue
        left_logical = exprs[0].get("op", "").strip("[]")
        right_logical = exprs[1].get("op", "").strip("[]")

        conn = ds.find("connection")
        col_table: dict[str, str] = {}
        col_physical: dict[str, str] = {}
        if conn is not None:
            for m in conn.findall("./cols/map"):
                key = m.get("key", "").strip("[]")
                value = m.get("value", "")
                parts = value.strip("[]").split("].[")
                if len(parts) == 2:
                    col_table[key] = parts[0]
                    col_physical[key] = parts[1]

        left_table = col_table.get(left_logical, "")
        left_col = col_physical.get(left_logical, left_logical)
        right_table = col_table.get(right_logical, "")
        right_col = col_physical.get(right_logical, right_logical)

        rels.append({
            "from_table": left_table,
            "from_column": left_col,
            "to_table": right_table,
            "to_column": right_col,
        })
    return rels


def _parse_title(ws: ET.Element) -> dict | None:
    """Extract worksheet title text and run-level formatting.

    Returns None when no custom <title> element exists (PBI omits the title block).
    For multi-run titles the text of all static runs is joined; formatting is taken
    from the first static run.  CDATA dynamic field refs are skipped.
    Tableau-proprietary fonts (prefix 'Tableau ') are dropped so PBI falls back to
    its default font; bold/italic weight is preserved as a separate property.
    """
    runs = ws.findall("./layout-options/title/formatted-text/run")
    if not runs:
        return None

    text_parts: list[str] = []
    formatting: dict = {}

    for run in runs:
        text = (run.text or "").strip()
        is_dynamic = text.startswith("<[")

        # Accumulate static text
        if text and not is_dynamic:
            text_parts.append(text)

        # Capture formatting from the first run that carries any style attribute,
        # regardless of whether it also has text (Tableau sometimes separates them).
        if not formatting and any(run.get(a) for a in ("fontsize", "fontname", "fontcolor", "bold", "italic", "underline")):
            if run.get("fontsize"):
                formatting["font_size"] = int(float(run.get("fontsize")))
            fontname = run.get("fontname", "")
            if fontname and not fontname.lower().startswith("tableau "):
                formatting["font_family"] = fontname
            if run.get("fontcolor"):
                formatting["font_color"] = run.get("fontcolor")
            if run.get("bold") == "true":
                formatting["bold"] = True
            if run.get("italic") == "true":
                formatting["italic"] = True
            if run.get("underline") == "true":
                formatting["underline"] = True

    text = " ".join(text_parts).strip()
    if not text:
        return None
    return {"text": text, **formatting}


def _parse_sheets(root: ET.Element) -> list[dict]:
    """Extract worksheet definitions."""
    sheets = []
    for ws in root.findall("./worksheets/worksheet"):
        name = ws.get("name", "")
        deps = ws.find("./table/view/datasource-dependencies")
        datasource = deps.get("datasource", "") if deps is not None else ""
        rows_text = ws.findtext("./table/rows", "")
        cols_text = ws.findtext("./table/cols", "")
        mark = ws.find("./table/panes/pane/mark")
        mark_type = mark.get("class", "Automatic") if mark is not None else "Automatic"
        mark_orientation = mark.get("orientation", "") if mark is not None else ""
        label_fmt = ws.find(
            "./table/panes/pane/style/style-rule[@element='mark']/format[@attr='mark-labels-show']"
        )
        show_data_labels = label_fmt is not None and label_fmt.get("value") == "true"

        # Tableau text tables (crosstabs) encode their measures in <encodings><text>,
        # not on the cols shelf. Gate: only treat as text table when cols is empty,
        # rows is non-empty, mark is Automatic, and text encoding fields exist.
        text_enc_fields = []
        for text_enc in ws.findall("./table/panes/pane/encodings/text"):
            col_attr = text_enc.get("column", "")
            if col_attr:
                text_enc_fields.extend(_parse_shelf_fields(col_attr))

        is_text_table = (
            mark_type == "Automatic"
            and bool(rows_text.strip())
            and not cols_text.strip()
            and bool(text_enc_fields)
        )
        if is_text_table:
            col_fields = text_enc_fields
            mark_type = "Text"
        else:
            col_fields = _parse_shelf_fields(cols_text)

        sheets.append({
            "name": name,
            "title": _parse_title(ws),
            "datasource": datasource,
            "rows": _parse_shelf_fields(rows_text),
            "cols": col_fields,
            "mark_type": mark_type,
            "mark_orientation": mark_orientation,
            "show_data_labels": show_data_labels,
            "filters": _parse_filters(ws),
            "sorts": _parse_sorts(ws),
        })
    return sheets


def _parse_filter_element(f: ET.Element) -> dict | None:
    """Parse a single <filter> element into a filter dict. Returns None for virtual fields."""
    col = f.get("column", "")
    cls = f.get("class", "")
    if "].[" in col:
        field_ref = col.split("].[", 1)[1].rstrip("]")
    else:
        field_ref = col.strip("[]")
    segments = field_ref.split(":", 2)
    name = segments[1] if len(segments) == 3 else field_ref
    if name.startswith(":"):
        return None
    entry: dict = {"field": name, "class": cls}
    if cls == "categorical":
        # member attribute is encoded as '"value"' in Tableau XML
        members = [
            gf.get("member", "").strip('"')
            for gf in f.iter("groupfilter")
            if gf.get("function") == "member"
        ]
        if members:
            entry["values"] = members
    elif cls == "quantitative":
        if len(segments) == 3 and segments[0] in _AGG_MAP:
            entry["agg_prefix"] = segments[0]
        entry["min"] = f.findtext("min", "")
        entry["max"] = f.findtext("max", "")
    return entry


def _parse_filters(ws: ET.Element) -> list[dict]:
    """Extract worksheet-level filters from a <worksheet> element."""
    filters = []
    for f in ws.findall("./table/view/filter"):
        entry = _parse_filter_element(f)
        if entry is not None:
            filters.append(entry)
    return filters


def _parse_sorts(ws: ET.Element) -> list[dict]:
    """Extract worksheet-level sorts from <computed-sort>, <natural-sort>, <alphabetic-sort>, <manual-sort>."""
    sorts = []
    view = ws.find("./table/view")
    if view is None:
        return sorts

    for tag, sort_type in [
        ("computed-sort", "computed"),
        ("natural-sort", "natural"),
        ("alphabetic-sort", "alphabetic"),
        ("manual-sort", "manual"),
    ]:
        for el in view.findall(tag):
            col = el.get("column", "")
            direction = el.get("direction", "ASC")
            field_name = _extract_field_name(col)
            if not field_name:
                continue
            entry: dict = {"type": sort_type, "field": field_name, "direction": direction}
            if sort_type == "computed":
                using = el.get("using", "")
                using_ref = _extract_field_ref(using)
                segs = using_ref.split(":", 2)
                entry["using_prefix"] = segs[0] if len(segs) == 3 else ""
                entry["using"] = segs[1] if len(segs) == 3 else using_ref
            sorts.append(entry)
    return sorts


def _extract_field_name(col_attr: str) -> str:
    """Extract the middle segment (field name) from a Tableau column attribute."""
    ref = _extract_field_ref(col_attr)
    segs = ref.split(":", 2)
    return segs[1] if len(segs) == 3 else ref


def _extract_field_ref(col_attr: str) -> str:
    """Strip the datasource prefix from a [ds].[prefix:name:suffix] attribute."""
    if "].[" in col_attr:
        return col_attr.split("].[", 1)[1].rstrip("]")
    return col_attr.strip("[]")


def _parse_datasource_filters(root: ET.Element) -> list[dict]:
    """Extract filters from <shared-views> that apply across all sheets."""
    filters = []
    for sv in root.findall("./shared-views/shared-view"):
        for f in sv.findall("filter"):
            entry = _parse_filter_element(f)
            if entry is not None:
                filters.append(entry)
    return filters


_DISCRETE_PREFIXES = {"none", "yr", "qr", "mn", "wk", "dt", "hr", "mt", "sg"}

_DATE_PART_MAP = {
    "yr": "YEAR",
    "qr": "QUARTER",
    "mn": "MONTH",
    "wk": "WEEKNUM",
    "hr": "HOUR",
}

_AGG_MAP = {
    "ctd": "DISTINCTCOUNT",
    "cntd": "DISTINCTCOUNT",
    "cnt": "COUNTA",
    "sum": "SUM",
    "avg": "AVERAGE",
    "min": "MIN",
    "max": "MAX",
    "median": "MEDIAN",
    "var": "VAR.S",
    "varp": "VAR.P",
    "stdev": "STDEV.S",
    "stdevp": "STDEV.P",
}


def _parse_shelf_fields(shelf: str) -> list[dict]:
    """Parse shelf string into list of {name, continuous, aggregation} dicts."""
    if not shelf.strip():
        return []
    text = shelf.strip()
    # Tableau wraps compound measure lists in parens: (field1 + field2)
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    parts = [p.strip() for p in text.replace(" + ", ",").replace(" / ", ",").split(",")]
    fields = []
    for part in parts:
        if "].[" in part:
            field_ref = part.split("].[", 1)[1].rstrip("]")
        else:
            field_ref = part.strip("[]")
        segments = field_ref.split(":", 2)
        if len(segments) == 3:
            prefix, name, _ = segments
            continuous = prefix not in _DISCRETE_PREFIXES
            aggregation = _AGG_MAP.get(prefix)
        else:
            name = field_ref
            continuous = False
            aggregation = None
        if name.startswith(":"):
            continue  # Tableau virtual field (e.g. :Measure Names, :Measure Values)
        date_part = _DATE_PART_MAP.get(prefix) if len(segments) == 3 else None
        fields.append({"name": name, "continuous": continuous, "aggregation": aggregation, "date_part": date_part})
    return fields


_SUPPORTED_CONN_TYPES = {"excel-direct", "textscan", "csv", "postgres", "sqlserver", "mysql", "bigquery", "redshift", "snowflake", "oracle", ""}
_SQL_CONN_TYPES = {"postgres", "sqlserver", "mysql", "bigquery", "redshift", "snowflake", "oracle"}
_UNSUPPORTED_RELATION_TYPES = {"union", "batch-union", "subquery", "stored-proc", "pivot", "project"}


def _detect_unsupported(root: ET.Element, datasources: list[dict]) -> list[str]:
    """Detect and return descriptions of unsupported patterns."""
    issues = []

    for ds in datasources:
        conn = ds.get("connection", {})
        conn_type = conn.get("type", "")
        if conn_type not in _SUPPORTED_CONN_TYPES:
            issues.append(
                f"Datasource '{ds['name']}': unsupported connection type '{conn_type}'"
            )
        # Live connections use DirectQuery — note in report for user awareness
        if conn.get("live_connection"):
            issues.append(
                f"Datasource '{ds['name']}': live SQL connection — generated as DirectQuery mode"
            )

    for rel in root.iter("relation"):
        rtype = rel.get("type", "")
        if rtype == "text":
            name = rel.get("name", "unnamed")
            issues.append(f"Custom SQL relation '{name}' detected — wrapped in Value.NativeQuery for SQL sources")
        elif rtype in _UNSUPPORTED_RELATION_TYPES:
            name = rel.get("name", rtype)
            issues.append(f"Relation type '{rtype}' ('{name}') is not supported")

    # Data blending: sheet referencing more than one non-Parameters datasource
    for ws in root.findall("./worksheets/worksheet"):
        sheet_name = ws.get("name", "")
        deps = [
            d.get("datasource", "")
            for d in ws.findall("./table/view/datasource-dependencies")
            if "Parameters" not in d.get("datasource", "")
        ]
        if len(deps) > 1:
            issues.append(
                f"Sheet '{sheet_name}': data blending across {deps} — not supported"
            )

    return issues
