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
        # Skip Tableau built-in datasources (Parameters, etc.)
        if name in ("Parameters",) or not name:
            continue

        connection = _parse_connection(ds)
        columns = _parse_columns(ds)
        calculated_fields = _parse_calculated_fields(ds)
        joins = _parse_joins(ds)

        results.append({
            "name": name,
            "caption": ds.get("caption", name),
            "connection": connection,
            "columns": columns,
            "calculated_fields": calculated_fields,
            "joins": joins,
        })
    return results


def _parse_connection(ds: ET.Element) -> dict:
    """Extract connection details: type, filename/server, table."""
    conn = ds.find("connection")
    if conn is None:
        return {}

    conn_class = conn.get("class", "")

    if conn_class == "federated":
        # Unwrap to the named real connection
        named = conn.find("./named-connections/named-connection/connection")
        if named is not None:
            actual_class = named.get("class", "")
            filename = named.get("filename", "")
            server = named.get("server", "")
        else:
            actual_class = filename = server = ""

        relation = conn.find("relation")
        table = relation.get("table", "").strip("[]") if relation is not None else ""
        table_name = relation.get("name", "") if relation is not None else ""
    else:
        actual_class = conn_class
        filename = conn.get("filename", "")
        server = conn.get("server", "")
        relation = conn.find("relation")
        table = relation.get("table", "").strip("[]") if relation is not None else ""
        table_name = relation.get("name", "") if relation is not None else ""

    return {
        "type": actual_class,
        "filename": filename,
        "server": server,
        "table": table,
        "table_name": table_name,
    }


def _parse_columns(ds: ET.Element) -> list[dict]:
    """Extract column definitions from the relation inside the connection."""
    cols = []
    for col in ds.findall("./connection/relation/columns/column"):
        cols.append({
            "name": col.get("name", ""),
            "datatype": col.get("datatype", ""),
        })
    return cols


def _parse_calculated_fields(ds: ET.Element) -> list[dict]:
    """Extract calculated field definitions."""
    fields = []
    for col in ds.findall("./column"):
        formula = col.find("calculation")
        if formula is not None:
            fields.append({
                "name": col.get("caption", col.get("name", "")),
                "formula": formula.get("formula", ""),
            })
    return fields


def _parse_joins(ds: ET.Element) -> list[dict]:
    """Extract join definitions (inner/left with explicit keys)."""
    joins = []
    for rel in ds.findall("./connection/relation[@type='join']"):
        joins.append({
            "type": rel.get("join", ""),
            "left": rel.get("left", ""),
            "right": rel.get("right", ""),
        })
    return joins


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
        })
    return sheets


def _parse_shelf_fields(shelf: str) -> list[str]:
    """Parse shelf string like '[ds].[field]' into a list of field references."""
    if not shelf.strip():
        return []
    # Split on commas (multiple fields) then strip ds prefix
    parts = [p.strip() for p in shelf.split(",")]
    fields = []
    for part in parts:
        # Format: [datasource].[field_ref]
        if "].[" in part:
            field_ref = part.split("].[", 1)[1].rstrip("]")
        else:
            field_ref = part.strip("[]")
        fields.append(field_ref)
    return fields


def _detect_unsupported(root: ET.Element, datasources: list[dict]) -> list[str]:
    """Detect and return descriptions of unsupported patterns."""
    issues = []

    for ds in datasources:
        conn = ds.get("connection", {})
        conn_type = conn.get("type", "")

        if conn_type not in ("excel-direct", "textscan", "csv", ""):
            issues.append(
                f"Datasource '{ds['name']}': unsupported connection type '{conn_type}'"
            )

        if ds.get("joins"):
            issues.append(
                f"Datasource '{ds['name']}': joins detected (not yet supported)"
            )

    # Detect custom SQL
    for custom_sql in root.iter("relation"):
        if custom_sql.get("type") == "text":
            issues.append("Custom SQL relation detected (not supported)")

    return issues
