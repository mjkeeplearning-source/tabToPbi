"""Parse .twb / .twbx files into a workbook dict."""

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


_NAMED_TOKENS = {
    "<Sheet Name>": "sheet_name",
    "<Workbook Name>": "workbook_name",
    "<Data Connection Name>": "data_connection_name",
    "<Default Caption>": "default_caption",
    "<Page Name>": "page_name",
    "<Page Number>": "page_number",
    "<Page Count>": "page_count",
    "<Data Update Time>": "data_update_time",
    "<Full Name>": "user_full_name",
    "<User Name>": "user_name",
}


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
        "window_filter_cards": _parse_window_filter_cards(root),
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


def _build_query_caption_map(ds: ET.Element) -> dict[str, str]:
    """Build {relation_name → logical_caption} from the object-graph.

    e.g. {"Custom SQL Query" → "Customers", "Custom SQL Query1" → "Orders"}
    Used to replace generic Tableau-internal query aliases with user-facing names.
    """
    result: dict[str, str] = {}
    for obj in ds.findall("./object-graph/objects/object"):
        caption = obj.get("caption", "")
        rel = obj.find("./properties/relation")
        if caption and rel is not None:
            qname = rel.get("name", "")
            if qname:
                result[qname] = caption
    return result


def _parse_datasources(root: ET.Element) -> tuple[list[dict], list[str]]:
    """Extract datasource info. Returns (datasources, physical_join_flags)."""
    results = []
    all_join_flags: list[str] = []
    for ds in root.findall("./datasources/datasource"):
        name = ds.get("name", "")
        if name in ("Parameters",) or not name:
            continue

        query_caption_map = _build_query_caption_map(ds)
        connection = _parse_connection(ds, query_caption_map)
        tables = _parse_tables(ds, connection, query_caption_map)
        columns = _parse_columns(ds, connection, query_caption_map)
        calculated_fields = _parse_calculated_fields(ds)
        logical_rels = _parse_relationships(ds, query_caption_map)
        physical_rels, join_flags = _parse_physical_joins(ds.find("connection"))
        all_join_flags.extend(join_flags)
        relationships = logical_rels + physical_rels
        calc_name_map = {cf["internal_name"]: cf["name"] for cf in calculated_fields}
        column_formats = _parse_column_formats(ds)
        object_id_map = _parse_object_id_map(ds)
        color_palettes = _parse_datasource_color_palette(ds)

        results.append({
            "name": name,
            "caption": ds.get("caption", name),
            "connection": connection,
            "tables": tables,
            "columns": columns,
            "calculated_fields": calculated_fields,
            "calc_name_map": calc_name_map,
            "relationships": relationships,
            "column_formats": column_formats,
            "object_id_map": object_id_map,
            "color_palettes": color_palettes,
        })
    return results, all_join_flags


def _parse_connection(ds: ET.Element, query_caption_map: dict | None = None) -> dict:
    """Extract connection details."""
    qcmap = query_caption_map or {}
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
            http_path = named.get("v-http-path", "")
            warehouse = named.get("warehouse", "")
        else:
            actual_class = filename = server = dbname = port = username = http_path = warehouse = ""

        relation = conn.find("relation")
        rel_type = relation.get("type", "") if relation is not None else ""
        table = ""
        table_name = ""
        custom_sql = ""
        if relation is not None and rel_type == "text":
            custom_sql = (relation.text or "").strip()
            raw_name = relation.get("name", "Custom SQL Query")
            table_name = qcmap.get(raw_name, raw_name)
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
        http_path = ""
        warehouse = conn.get("warehouse", "")
        relation = conn.find("relation")
        custom_sql = ""
        if relation is not None and relation.get("type") == "text":
            custom_sql = (relation.text or "").strip()
            table = ""
            raw_name = relation.get("name", "Custom SQL Query")
            table_name = qcmap.get(raw_name, raw_name)
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
        "http_path": http_path,
        "warehouse": warehouse,
        "table": table,
        "table_name": table_name,
        "custom_sql": custom_sql,
        "live_connection": live_connection,
    }


def _parse_tables(ds: ET.Element, connection: dict, query_caption_map: dict | None = None) -> list[dict]:
    """Extract physical table list. For collection relations returns all child tables."""
    qcmap = query_caption_map or {}
    conn = ds.find("connection")
    if conn is None:
        return []

    relation = conn.find("relation")
    if relation is None:
        return []

    if relation.get("type") == "collection":
        tables = []
        for child in relation.findall("relation[@type='table']"):
            raw_table = child.get("table", "")  # e.g. [schema].[table] or [cat].[schema].[table]
            parts = raw_table.strip("[]").split("].[")
            schema = parts[-2] if len(parts) >= 2 else ""
            table = parts[-1] if len(parts) >= 1 else raw_table.strip("[]")
            tables.append({
                "name": child.get("name", table),
                "schema": schema,
                "table": table,
            })
        if not tables:
            # Collection of custom SQL queries — each child is type="text"
            for child in relation.findall("relation[@type='text']"):
                raw_name = child.get("name", "Custom SQL Query")
                name = qcmap.get(raw_name, raw_name)
                sql = (child.text or "").strip()
                tables.append({"name": name, "schema": "", "table": name, "custom_sql": sql})
        return tables

    if relation.get("type") == "join":
        tables = []
        for r in relation.iter("relation"):
            if r.get("type") == "table":
                raw_table = r.get("table", "")
                parts = raw_table.strip("[]").split("].[")
                schema = parts[-2] if len(parts) >= 2 else ""
                table_name = parts[-1] if len(parts) >= 1 else raw_table.strip("[]")
                tables.append({
                    "name": r.get("name", table_name),
                    "schema": schema,
                    "table": table_name,
                })
        if not tables:
            # Join of custom SQL queries — each direct child is type="text"
            for child in relation.iter("relation"):
                if child.get("type") == "text":
                    raw_name = child.get("name", "Custom SQL Query")
                    name = qcmap.get(raw_name, raw_name)
                    sql = (child.text or "").strip()
                    tables.append({"name": name, "schema": "", "table": name, "custom_sql": sql})
        return tables

    # Single table
    table_name = connection.get("table_name") or connection.get("table", "")
    if table_name:
        return [{"name": table_name, "schema": "", "table": table_name}]
    return []


def _parse_columns(ds: ET.Element, connection: dict, query_caption_map: dict | None = None) -> list[dict]:
    """Extract columns with source_table info.

    For collection (multi-table): uses metadata-records (has parent-name) and
    cols/map to build source_table assignment.
    For single-table: uses relation/columns/column elements.
    """
    qcmap = query_caption_map or {}
    conn = ds.find("connection")
    if conn is None:
        return []

    relation = conn.find("relation")
    if relation is not None and relation.get("type") in ("collection", "join"):
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
            resolved_parent = qcmap.get(parent_name, parent_name)
            source_table = col_table.get(local_name, "") or resolved_parent
            remote_name = col_physical.get(local_name, local_name)
            if local_name:
                cols.append({
                    "name": local_name,
                    "remote_name": remote_name,
                    "datatype": local_type,
                    "source_table": source_table,
                })
        return cols

    # Custom SQL: columns are in metadata-records on the connection element
    if relation is not None and relation.get("type") == "text":
        table_name = connection.get("table_name", "Custom SQL Query")
        cols = []
        for mr in conn.findall("./metadata-records/metadata-record[@class='column']"):
            local_name = mr.findtext("local-name", "").strip("[]")
            local_type = mr.findtext("local-type", "string")
            if local_name:
                cols.append({
                    "name": local_name,
                    "remote_name": local_name,
                    "datatype": local_type,
                    "source_table": table_name,
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


def _parse_column_formats(ds: ET.Element) -> dict[str, str]:
    """Return {column_name: format_string} for columns with a default-format attribute."""
    result: dict[str, str] = {}
    for col in ds.findall("./column"):
        fmt = col.get("default-format", "")
        if fmt:
            name = col.get("name", "").strip("[]")
            caption = col.get("caption", "")
            if name:
                result[name] = fmt
            if caption and caption != name:
                result[caption] = fmt
    return result


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
    """Extract relationships from physical-layer join relations (nested tree).

    Recursively walks the join tree. INNER + LEFT + RIGHT → PBI relationships
    (RIGHT is flipped). FULL OUTER is noted in flags but still extracted — PBI
    determines join semantics from cardinality, not join type.
    Returns (relationships, unsupported_flags).
    """
    rels: list[dict] = []
    flags: list[str] = []
    if conn is None:
        return rels, flags
    top_rel = conn.find("relation")
    if top_rel is None or top_rel.get("type") != "join":
        return rels, flags
    _walk_join(top_rel, rels, flags)
    return rels, flags


def _split_table_col(op: str) -> tuple[str, str]:
    """Split a [Table].[Column] expression into (table, column)."""
    parts = op.strip("[]").split("].[")
    return (parts[0], parts[1]) if len(parts) == 2 else ("", op)


def _walk_join(rel: ET.Element, rels: list[dict], flags: list[str]) -> None:
    """Recursively extract one relationship per join node in the tree."""
    # Recurse into child join nodes first (left-subtree joins)
    for child in rel.findall("relation[@type='join']"):
        _walk_join(child, rels, flags)

    join_type = rel.get("join", "inner").lower().replace(" ", "")

    if join_type in ("full", "fullouter", "fullouterjoin"):
        right_children = rel.findall("relation")
        right_name = right_children[-1].get("name", "?") if right_children else "?"
        flags.append(
            f"FULL OUTER join involving '{right_name}' — "
            "migrated as oneToOne relationship; FULL OUTER semantics not supported in PBI"
        )

    exprs = rel.findall("./clause[@type='join']/expression[@op='=']/expression")
    if len(exprs) != 2:
        flags.append("Non-equi join detected — not supported")
        return

    left_table, left_col = _split_table_col(exprs[0].get("op", ""))
    right_table, right_col = _split_table_col(exprs[1].get("op", ""))

    if join_type in ("right", "rightouter"):
        left_table, left_col, right_table, right_col = right_table, right_col, left_table, left_col

    rels.append({
        "from_table": left_table,
        "from_column": left_col,
        "to_table": right_table,
        "to_column": right_col,
        "join_type": join_type,
    })


def _parse_relationships(ds: ET.Element, query_caption_map: dict | None = None) -> list[dict]:
    """Extract relationships from object-graph (Tableau logical layer)."""
    qcmap = query_caption_map or {}
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
            # Fallback for custom SQL collections: no cols/map, resolve via metadata-records parent-name
            if not col_table:
                for mr in conn.findall("./metadata-records/metadata-record[@class='column']"):
                    local_name = mr.findtext("local-name", "").strip("[]")
                    parent_name = mr.findtext("parent-name", "").strip("[]")
                    if local_name and parent_name:
                        col_table[local_name] = qcmap.get(parent_name, parent_name)
                        col_physical[local_name] = local_name

        left_table = col_table.get(left_logical, "")
        left_col = col_physical.get(left_logical, left_logical)
        right_table = col_table.get(right_logical, "")
        right_col = col_physical.get(right_logical, right_logical)

        first_ep = rel.find("first-end-point")
        second_ep = rel.find("second-end-point")
        first_unique = first_ep is not None and first_ep.get("unique-key") == "true"
        second_unique = second_ep is not None and second_ep.get("unique-key") == "true"

        rels.append({
            "from_table": left_table,
            "from_column": left_col,
            "to_table": right_table,
            "to_column": right_col,
            "first_unique_key": first_unique,
            "second_unique_key": second_unique,
        })
    return rels


def _parse_object_id_map(ds: ET.Element) -> dict[str, str]:
    """Build {object_id → logical_table_name} from the object-graph.

    Uses the object caption (e.g. "Customers") rather than the relation name
    (e.g. "Custom SQL Query") so the map stays consistent with PBI table names.
    """
    result = {}
    for obj in ds.findall("./object-graph/objects/object"):
        oid = obj.get("id", "")
        rel = obj.find("./properties/relation")
        if oid and rel is not None:
            result[oid] = obj.get("caption", "") or rel.get("name", "")
    return result


def _parse_title(ws: ET.Element) -> dict | None:
    """Extract worksheet title runs and formatting.

    Returns None when no custom <title> element exists.
    Each run is classified as one of:
      {"kind": "text",     "value": "..."}   — static text
      {"kind": "token",    "token": "..."}   — named system token (e.g. sheet_name)
      {"kind": "field_ref","value": "..."}   — field-reference token (CDATA, unresolvable)
    Formatting is captured from the first styled run.
    Tableau-proprietary fonts (prefix 'Tableau ') are dropped.
    """
    runs = ws.findall("./layout-options/title/formatted-text/run")
    if not runs:
        return None

    parsed_runs: list[dict] = []
    formatting: dict = {}

    for run in runs:
        text = run.text or ""

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

        stripped = text.strip()
        if not stripped:
            continue

        if stripped in _NAMED_TOKENS:
            parsed_runs.append({"kind": "token", "token": _NAMED_TOKENS[stripped]})
        elif re.search(r"<\[", stripped):
            parsed_runs.append({"kind": "field_ref", "value": stripped})
        else:
            # Strip Tableau run-separator chars (Æ + newline used between styled runs)
            cleaned = stripped.replace("Æ", "").strip()
            if cleaned:
                parsed_runs.append({"kind": "text", "value": text})

    if not parsed_runs:
        return None

    return {"runs": parsed_runs, "formatting": formatting}


def _field_axis(field_attr: str) -> str:
    """Return 'value' or 'category' based on Tableau field column-instance derivation prefix."""
    if "].[" in field_attr:
        field_attr = field_attr.split("].[", 1)[1].rstrip("]")
    prefix = field_attr.split(":", 1)[0].lower()
    return "value" if prefix == "usr" else "category"


# Tableau line-pattern-only values → PBI gridlineStyle literals
_GRIDLINE_STYLE_MAP = {
    "solid": "solid",
    "dotted": "dotted",
    "dashed": "dashed",
}

# Tableau style-rule elements that have no PBI chart equivalent
_UNSUPPORTED_FORMAT_ELEMENTS = {
    "cell", "header", "field-labels-decoration", "field-labels-spanner",
    "dropline", "refline", "zeroline", "table",
}


def _parse_worksheet_format(ws: ET.Element) -> dict:
    """Parse Tableau <style> rules into a normalized visual_format dict.

    Returns dict with keys: value_axis, category_axis, both_axes_title,
    plot_area, unsupported_elements.  Each axis dict may contain:
    label_font_family, label_font_size, axis_color, gridline_show, gridline_style.
    both_axes_title may contain: font_family, font_size, bold.
    plot_area may contain: background_color.
    """
    style = ws.find("./table/style")
    if style is None:
        return {}

    value_axis: dict = {}
    category_axis: dict = {}
    both_axes_title: dict = {}
    plot_area: dict = {}
    unsupported: list[str] = []

    for rule in style.findall("style-rule"):
        element = rule.get("element", "")

        if element == "label":
            for fmt in rule.findall("format"):
                attr = fmt.get("attr", "")
                value = fmt.get("value", "")
                field = fmt.get("field", "")
                if not attr or not value:
                    continue
                axis = value_axis if _field_axis(field) == "value" else category_axis
                if attr == "font-family" and "label_font_family" not in axis:
                    if not value.lower().startswith("tableau "):
                        axis["label_font_family"] = value
                elif attr == "font-size" and "label_font_size" not in axis:
                    axis["label_font_size"] = int(float(value))

        elif element == "axis":
            for fmt in rule.findall("format"):
                attr = fmt.get("attr", "")
                value = fmt.get("value", "")
                scope = fmt.get("scope", "")
                if attr == "stroke-color":
                    # rows scope = Y-axis = value axis; cols scope = X-axis = category axis
                    target = value_axis if scope == "rows" else category_axis
                    if "axis_color" not in target:
                        target["axis_color"] = value
                elif attr == "title":
                    target = value_axis if scope == "rows" else category_axis
                    if "title_text" not in target:
                        target["title_text"] = value

        elif element == "field-labels":
            for fmt in rule.findall("format"):
                attr = fmt.get("attr", "")
                value = fmt.get("value", "")
                if not value:
                    continue
                if attr == "font-family" and "font_family" not in both_axes_title:
                    if not value.lower().startswith("tableau "):
                        both_axes_title["font_family"] = value
                elif attr == "font-size" and "font_size" not in both_axes_title:
                    both_axes_title["font_size"] = int(float(value))
                elif attr == "font-weight" and value == "bold":
                    both_axes_title["bold"] = True

        elif element == "pane":
            for fmt in rule.findall("format"):
                if fmt.get("attr") == "background-color" and not fmt.get("data-class"):
                    if "background_color" not in plot_area:
                        plot_area["background_color"] = fmt.get("value", "")

        elif element == "gridline":
            for fmt in rule.findall("format"):
                attr = fmt.get("attr", "")
                value = fmt.get("value", "")
                scope = fmt.get("scope", "")
                target = value_axis if scope == "rows" else category_axis
                if attr == "line-visibility":
                    if "gridline_show" not in target:
                        target["gridline_show"] = value == "on"
                elif attr == "line-pattern-only":
                    if "gridline_style" not in target and value in _GRIDLINE_STYLE_MAP:
                        target["gridline_style"] = _GRIDLINE_STYLE_MAP[value]

        elif element in _UNSUPPORTED_FORMAT_ELEMENTS:
            unsupported.append(element)

    # mark-color lives in pane/style, not table/style — check pane path directly
    mark_color_fmt = ws.find(
        "./table/panes/pane/style/style-rule[@element='mark']/format[@attr='mark-color']"
    )
    if mark_color_fmt is not None:
        plot_area["mark_color"] = mark_color_fmt.get("value", "")

    result: dict = {}
    if value_axis:
        result["value_axis"] = value_axis
    if category_axis:
        result["category_axis"] = category_axis
    if both_axes_title:
        result["both_axes_title"] = both_axes_title
    if plot_area:
        result["plot_area"] = plot_area
    if unsupported:
        result["unsupported_elements"] = list(dict.fromkeys(unsupported))  # deduplicate, preserve order
    return result


def _parse_datasource_color_palette(ds: ET.Element) -> dict[str, dict[str, str]]:
    """Return {field_name: {value: hex}} from datasource color palette encodings."""
    result: dict[str, dict[str, str]] = {}
    for enc in ds.findall('.//encoding[@attr="color"][@type="palette"]'):
        field_attr = enc.get("field", "").strip("[]")
        segs = field_attr.split(":", 2)
        field_name = segs[1] if len(segs) >= 2 else field_attr
        if not field_name:
            continue
        palette: dict[str, str] = {}
        for m in enc.findall("map"):
            hex_color = m.get("to", "")
            bucket = (m.findtext("bucket") or "").strip('"')
            if hex_color and bucket:
                palette[bucket] = hex_color
        if palette:
            result[field_name] = palette
    return result


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

        # Color encoding (used by pie charts for legend, and heatmaps for intensity)
        color_enc_fields = []
        for enc in ws.findall("./table/panes/pane/encodings/color"):
            col_attr = enc.get("column", "")
            if col_attr:
                color_enc_fields.extend(_parse_shelf_fields(col_attr))

        # Wedge-size encoding (pie chart measure)
        wedge_enc_fields = []
        for enc in ws.findall("./table/panes/pane/encodings/wedge-size"):
            col_attr = enc.get("column", "")
            if col_attr:
                wedge_enc_fields.extend(_parse_shelf_fields(col_attr))

        # CrossTab: both shelves have content + text encoding is the virtual "Multiple Values"
        # field. Actual measures are listed in the :Measure Names categorical filter.
        is_crosstab = (
            mark_type == "Automatic"
            and bool(rows_text.strip())
            and bool(cols_text.strip())
            and any(f.get("name") == "Multiple Values" for f in text_enc_fields)
        )
        is_text_table = (
            mark_type == "Automatic"
            and bool(rows_text.strip())
            and not cols_text.strip()
            and bool(text_enc_fields)
        )
        # KPI/summary-number: both shelves empty, measure only in <encodings><text>.
        # Tableau renders this as a single large number; PBI equivalent is cardVisual.
        is_kpi = (
            mark_type == "Automatic"
            and not rows_text.strip()
            and not cols_text.strip()
            and bool(text_enc_fields)
        )
        rows_parsed = _parse_shelf_fields(rows_text)
        if is_crosstab:
            col_fields = _parse_shelf_fields(cols_text)
            crosstab_measures = _extract_measure_names_filter(ws)
            mark_type = "CrossTab"
            encoding_fields = []
            # Attach crosstab measures so transformer can place them in Values role
            _crosstab_measures_tmp = crosstab_measures
        elif is_text_table:
            col_fields = text_enc_fields
            mark_type = "Text"
            encoding_fields: list[dict] = []
        elif is_kpi:
            col_fields = text_enc_fields
            mark_type = "KPI"
            encoding_fields = []
        elif mark_type == "Pie" and color_enc_fields:
            # Pie uses encodings instead of row/col shelves: color=legend, wedge=values.
            # Fall back to text_enc_fields when no explicit wedge-size encoding exists
            # (measure placed on the Text shelf only — Tableau renders equal slices with labels).
            rows_parsed = color_enc_fields
            col_fields = wedge_enc_fields or text_enc_fields
            encoding_fields = []
        else:
            col_fields = _parse_shelf_fields(cols_text)
            # Color encoding on non-pie marks (e.g. heatmap intensity) — kept separate
            # so mark-type inference runs on shelf fields only, appended later
            encoding_fields = color_enc_fields

        sheet: dict = {
            "name": name,
            "title": _parse_title(ws),
            "datasource": datasource,
            "rows": rows_parsed,
            "cols": col_fields,
            "encoding_fields": encoding_fields,
            "color_dimension": color_enc_fields[0]["name"] if color_enc_fields else None,
            "mark_type": mark_type,
            "mark_orientation": mark_orientation,
            "show_data_labels": show_data_labels,
            "filters": _parse_filters(ws),
            "sorts": _parse_sorts(ws),
            "visual_format": _parse_worksheet_format(ws),
        }
        if is_crosstab:
            sheet["crosstab_measures"] = _crosstab_measures_tmp
        sheets.append(sheet)
    return sheets


def _extract_measure_names_filter(ws: ET.Element) -> list[dict]:
    """Extract actual measures from the :Measure Names categorical filter in a CrossTab sheet.

    Tableau encodes crosstab cell measures as members of a categorical filter on
    the virtual [:Measure Names] column, e.g. member="[ds].[sum:quantity:qk]".
    Returns a list of parsed measure dicts (name, aggregation, is_measure=True).
    """
    measures = []
    for f in ws.findall("./table/view/filter[@class='categorical']"):
        col = f.get("column", "")
        if "].[:" not in col:
            continue
        field_ref = col.split("].[", 1)[1].rstrip("]")
        if not field_ref.startswith(":Measure Names"):
            continue
        for gf in f.iter("groupfilter"):
            if gf.get("function") != "member":
                continue
            member = gf.get("member", "").strip('"')
            if "].[" in member:
                inner = member.split("].[", 1)[1].rstrip("]")
            else:
                inner = member.strip("[]")
            parsed = _parse_shelf_fields(f"[placeholder].[{inner}]")
            for field in parsed:
                field["is_measure"] = True
                measures.append(field)
    return measures


def _parse_filter_element(f: ET.Element) -> dict | None:
    """Parse a single <filter> element into a filter dict. Returns None for virtual fields."""
    col = f.get("column", "")
    cls = f.get("class", "")
    if "].[" in col:
        field_ref = col.split("].[", 1)[1].rstrip("]")
    else:
        field_ref = col.strip("[]")
    segments = field_ref.split(":", 2)
    prefix = segments[0] if len(segments) == 3 else ""
    name = segments[1] if len(segments) == 3 else field_ref
    if name.startswith(":"):
        return None
    entry: dict = {"field": name, "class": cls}
    date_part = _DATE_PART_MAP.get(prefix)
    if date_part:
        entry["date_part"] = date_part
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
        included = f.get("included-values", "")
        if included:
            entry["included_values"] = included
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


def _parse_window_filter_cards(root: ET.Element) -> dict[str, list[dict]]:
    """Return {sheet_name: [{"field": str, "mode": str}]} from <windows> filter cards.

    <windows> is authoritative: only sheets with a <card type='filter'> entry will
    have slicer visuals generated.
    """
    result: dict[str, list[dict]] = {}
    for window in root.findall("./windows/window[@class='worksheet']"):
        name = window.get("name", "")
        if not name:
            continue
        cards = []
        for card in window.findall("./cards/edge/strip/card[@type='filter']"):
            param = card.get("param", "")
            field = _extract_field_name(param) if param else ""
            if field and not field.startswith(":"):
                cards.append({"field": field, "mode": card.get("mode", "")})
        if cards:
            result[name] = cards
    return result


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

        # Tableau logical table pill: __tableau_internal_object_id__].[agg:object_id:suffix
        if field_ref.startswith("__tableau_internal_object_id__"):
            inner = field_ref.split("].[", 1)[1] if "].[" in field_ref else ""
            inner_parts = inner.split(":", 2)
            if len(inner_parts) == 3:
                agg, object_id, _ = inner_parts
                if agg and object_id:
                    fields.append({"name": object_id, "object_id": True, "aggregation": agg, "continuous": True, "date_part": None})
            continue

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


_SUPPORTED_CONN_TYPES = {"excel-direct", "textscan", "csv", "postgres", "sqlserver", "mysql", "bigquery", "redshift", "snowflake", "oracle", "teradata", "databricks", ""}
_SQL_CONN_TYPES = {"postgres", "sqlserver", "mysql", "bigquery", "redshift", "snowflake", "oracle", "teradata", "databricks"}
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

    seen_custom_sql: set[str] = set()
    for rel in root.iter("relation"):
        rtype = rel.get("type", "")
        if rtype == "text":
            name = rel.get("name", "unnamed")
            if name not in seen_custom_sql:
                seen_custom_sql.add(name)
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
