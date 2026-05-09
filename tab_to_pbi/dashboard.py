"""Tableau dashboard zones -> PBI dashboard pages."""

import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from tab_to_pbi.generator import MARK_TO_VISUAL, _VISUAL_ROLES, _make_projection

_SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report"
_PBI_W = 1280
_PBI_H = 720

_SLICER_MODE_MAP = {
    "dropdown": "Dropdown",
    "slider": "Between",
    "compact": "Dropdown",
    "type_in": "Dropdown",
    "radiolist": "Basic",
    "checkdropdown": "Dropdown",
}


def parse_dashboards_from_path(path: Path) -> list[dict]:
    """Parse dashboards from a .twb or .twbx file."""
    if path.suffix.lower() == ".twbx":
        with zipfile.ZipFile(path) as zf:
            twb_name = next(n for n in zf.namelist() if n.endswith(".twb"))
            with zf.open(twb_name) as f:
                root = ET.parse(f).getroot()
    else:
        root = ET.parse(path).getroot()
    return parse_dashboards(root)


def parse_dashboards(root: ET.Element) -> list[dict]:
    """Extract dashboard definitions from workbook XML root."""
    dashboards = []
    for dash in root.findall("./dashboards/dashboard"):
        name = dash.get("name", "")
        if not name:
            continue
        size = dash.find("size")
        width = int(size.get("minwidth", "1000")) if size is not None else 1000
        height = int(size.get("minheight", "620")) if size is not None else 620
        title_run = dash.find("./layout-options/title/formatted-text/run")
        title = (title_run.text or "").strip() if title_run is not None else name

        zones_el = dash.find("zones")
        zones = _flatten_zones(zones_el, title) if zones_el is not None else []

        dashboards.append({
            "name": name,
            "width": width,
            "height": height,
            "title": title,
            "zones": zones,
        })
    return dashboards


def _flatten_zones(el: ET.Element, dashboard_title: str) -> list[dict]:
    """Recursively walk zone tree, collecting leaf content zones with absolute coords."""
    results = []
    for zone in el.findall("zone"):
        type_v2 = zone.get("type-v2", "")
        name = zone.get("name", "")

        if type_v2 in ("layout-flow", "layout-basic"):
            results.extend(_flatten_zones(zone, dashboard_title))
        elif not type_v2 and name:
            results.append({
                "zone_type": "sheet",
                "name": name,
                "x": int(zone.get("x", 0)),
                "y": int(zone.get("y", 0)),
                "w": int(zone.get("w", 0)),
                "h": int(zone.get("h", 0)),
            })
        elif type_v2 == "filter":
            fz = _extract_filter_zone(zone)
            if fz:
                results.append(fz)
        elif type_v2 == "title":
            results.append({
                "zone_type": "title",
                "text": dashboard_title,
                "x": int(zone.get("x", 0)),
                "y": int(zone.get("y", 0)),
                "w": int(zone.get("w", 0)),
                "h": int(zone.get("h", 0)),
            })
        elif type_v2 == "text":
            tz = _extract_text_zone(zone)
            if tz:
                results.append(tz)
        # paramctrl, color, empty -> skip silently
    return results


def _extract_filter_zone(zone: ET.Element) -> dict | None:
    """Extract filter zone dict from a type-v2='filter' element."""
    param = zone.get("param", "")
    source_sheet = zone.get("name", "")
    if not param:
        return None
    if "].[" in param:
        ds_part, field_part = param.split("].[", 1)
        datasource_id = ds_part.lstrip("[")
        field_ref = field_part.rstrip("]")
    else:
        datasource_id = ""
        field_ref = param.strip("[]")

    segments = field_ref.split(":", 2)
    param_field = segments[1] if len(segments) == 3 else field_ref

    return {
        "zone_type": "filter",
        "name": source_sheet,
        "param_field": param_field,
        "param_datasource_id": datasource_id,
        "mode": zone.get("mode", ""),
        "x": int(zone.get("x", 0)),
        "y": int(zone.get("y", 0)),
        "w": int(zone.get("w", 0)),
        "h": int(zone.get("h", 0)),
    }


def _extract_text_zone(zone: ET.Element) -> dict | None:
    """Extract text zone dict from a type-v2='text' element."""
    run = zone.find("./formatted-text/run")
    text = (run.text or "").strip() if run is not None else ""
    if not text:
        return None
    return {
        "zone_type": "text",
        "text": text,
        "x": int(zone.get("x", 0)),
        "y": int(zone.get("y", 0)),
        "w": int(zone.get("w", 0)),
        "h": int(zone.get("h", 0)),
    }


# Stubs — implemented in later tasks
def transform_dashboards(dashboards: list[dict], workbook: dict, transformed: dict) -> list[dict]:
    return []


def write_dashboard_pages(dashboard_pages: list[dict], output_dir: Path, stem: str) -> list[dict]:
    return []
