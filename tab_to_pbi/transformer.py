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
    return {
        **workbook,
        "tables": tables,
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
