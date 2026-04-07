"""Transform parsed workbook dict into PBIR-ready structure."""


def transform(workbook: dict) -> dict:
    """Return transformed dict with DAX measures, PBI visuals, relationships. Stub for T1."""
    return {
        **workbook,
        "measures": [],
        "visuals": [],
        "relationships": [],
        "report": {},
    }
