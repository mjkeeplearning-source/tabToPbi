"""Parse .twb / .twbx files into a workbook dict."""

from pathlib import Path


def parse(path: Path) -> dict:
    """Return a workbook dict from a .twb or .twbx file. Stub for T1."""
    return {
        "name": path.stem,
        "datasources": [],
        "sheets": [],
        "unsupported": [],
    }
