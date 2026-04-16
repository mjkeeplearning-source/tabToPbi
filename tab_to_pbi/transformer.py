"""Transform parsed workbook dict into PBIR-ready structure."""

DATATYPE_MAP = {
    "string": "string",
    "integer": "int64",
    "real": "double",
    "date": "dateTime",
    "datetime": "dateTime",
    "boolean": "boolean",
}


def transform(workbook: dict) -> dict:
    """Return transformed dict with tables mapped to TMSL format."""
    tables = [_map_datasource(ds) for ds in workbook.get("datasources", [])]
    visuals = _process_sheets(workbook, tables)
    return {
        **workbook,
        "tables": tables,
        "visuals": visuals,
        "measures": [],
        "relationships": [],
    }


def _map_datasource(ds: dict) -> dict:
    """Map a parsed datasource to a TMSL table dict."""
    columns = [
        {
            "name": col["name"],
            "dataType": DATATYPE_MAP.get(col["datatype"], "string"),
            "sourceColumn": col["name"],
        }
        for col in ds["columns"]
    ]
    return {
        "name": ds["caption"],
        "connection": ds["connection"],
        "columns": columns,
    }


def _process_sheets(workbook: dict, tables: list[dict]) -> list[dict]:
    """Map sheets to visual descriptors referencing transformed table names."""
    ds_list = workbook.get("datasources", [])
    table_by_ds_name = {ds["name"]: tables[i] for i, ds in enumerate(ds_list) if i < len(tables)}

    visuals = []
    for sheet in workbook.get("sheets", []):
        table = table_by_ds_name.get(sheet["datasource"], {})
        fields = []
        for ref in sheet["rows"] + sheet["cols"]:
            name = _extract_field_name(ref)
            if name and name not in fields:
                fields.append(name)
        visuals.append({
            "name": sheet["name"],
            "table": table.get("name", ""),
            "fields": fields,
            "mark_type": sheet["mark_type"],
        })
    return visuals


def _extract_field_name(ref: str) -> str:
    """Extract column name from a Tableau field ref like 'none:Country/Region:nk'."""
    parts = ref.split(":", 2)
    if len(parts) == 3:
        return parts[1]
    return ref
