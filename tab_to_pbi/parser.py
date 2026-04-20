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

    datasources = _parse_datasources(root)
    sheets = _parse_sheets(root)
    unsupported = _detect_unsupported(root, datasources)

    return {
        "name": path.stem,
        "datasources": datasources,
        "sheets": sheets,
        "unsupported": unsupported,
    }


def _parse_twbx(path: Path) -> ET.Element:
    """Unzip .twbx and return the root element of the embedded .twb."""
    with zipfile.ZipFile(path) as zf:
        twb_name = next(n for n in zf.namelist() if n.endswith(".twb"))
        with zf.open(twb_name) as f:
            return ET.parse(f).getroot()


def _parse_datasources(root: ET.Element) -> list[dict]:
    """Extract datasource info from all non-builtin <datasource> elements."""
    results = []
    for ds in root.findall("./datasources/datasource"):
        name = ds.get("name", "")
        if name in ("Parameters",) or not name:
            continue

        connection = _parse_connection(ds)
        tables = _parse_tables(ds, connection)
        columns = _parse_columns(ds, connection)
        calculated_fields = _parse_calculated_fields(ds)
        relationships = _parse_relationships(ds)
        # internal Tableau name → display caption for shelf resolution
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
    return results


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
        # For single-table federated (non-collection)
        table = ""
        table_name = ""
        if relation is not None and rel_type != "collection":
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
        table = relation.get("table", "").strip("[]") if relation is not None else ""
        table_name = relation.get("name", "") if relation is not None else ""

    return {
        "type": actual_class,
        "filename": filename,
        "server": server,
        "dbname": dbname,
        "port": port,
        "username": username,
        "table": table,
        "table_name": table_name,
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
        # Build logical-name → source_table from cols/map
        col_table: dict[str, str] = {}
        for m in conn.findall("./cols/map"):
            key = m.get("key", "").strip("[]")          # e.g. "category"
            value = m.get("value", "")                   # e.g. "[orders].[category]"
            parts = value.strip("[]").split("].[")
            if len(parts) == 2:
                col_table[key] = parts[0]                # "orders"

        # Build columns from metadata-records
        cols = []
        for mr in conn.findall("./metadata-records/metadata-record[@class='column']"):
            local_name = mr.findtext("local-name", "").strip("[]")
            local_type = mr.findtext("local-type", "string")
            source_table = col_table.get(local_name, "")
            if local_name:
                cols.append({
                    "name": local_name,
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

        sheets.append({
            "name": name,
            "datasource": datasource,
            "rows": _parse_shelf_fields(rows_text),
            "cols": _parse_shelf_fields(cols_text),
            "mark_type": mark_type,
            "filters": _parse_filters(ws),
        })
    return sheets


def _parse_filters(ws: ET.Element) -> list[dict]:
    """Extract worksheet-level filters from a <worksheet> element."""
    filters = []
    for f in ws.iter("filter"):
        col = f.get("column", "")
        cls = f.get("class", "")
        if "].[" in col:
            field_ref = col.split("].[", 1)[1].rstrip("]")
        else:
            field_ref = col.strip("[]")
        segments = field_ref.split(":", 2)
        name = segments[1] if len(segments) == 3 else field_ref
        if name.startswith(":"):
            continue  # skip Tableau virtual fields
        entry: dict = {"field": name, "class": cls}
        if cls == "quantitative":
            entry["min"] = f.findtext("min", "")
            entry["max"] = f.findtext("max", "")
        filters.append(entry)
    return filters


_DISCRETE_PREFIXES = {"none", "yr", "qr", "mn", "wk", "dt", "hr", "mt", "sg"}

_AGG_MAP = {
    "ctd": "DISTINCTCOUNT",
    "cntd": "DISTINCTCOUNT",
    "cnt": "COUNTA",
    "sum": "SUM",
    "avg": "AVERAGE",
    "min": "MIN",
    "max": "MAX",
    "median": "MEDIAN",
}


def _parse_shelf_fields(shelf: str) -> list[dict]:
    """Parse shelf string into list of {name, continuous, aggregation} dicts."""
    if not shelf.strip():
        return []
    parts = [p.strip() for p in shelf.split(",")]
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
        fields.append({"name": name, "continuous": continuous, "aggregation": aggregation})
    return fields


_SUPPORTED_CONN_TYPES = {"excel-direct", "textscan", "csv", "postgres", ""}


def _detect_unsupported(root: ET.Element, datasources: list[dict]) -> list[str]:
    """Detect and return descriptions of unsupported patterns."""
    issues = []

    for ds in datasources:
        conn_type = ds.get("connection", {}).get("type", "")
        if conn_type not in _SUPPORTED_CONN_TYPES:
            issues.append(
                f"Datasource '{ds['name']}': unsupported connection type '{conn_type}'"
            )

    for custom_sql in root.iter("relation"):
        if custom_sql.get("type") == "text":
            issues.append("Custom SQL relation detected (not supported)")

    return issues
