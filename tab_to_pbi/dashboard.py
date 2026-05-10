"""Tableau dashboard zones -> PBI dashboard pages."""

import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from tab_to_pbi.generator import MARK_TO_VISUAL, _VISUAL_ROLES, _make_projection, _build_objects, _build_title_objects

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

# Tableau modes that are explicitly single-select; everything else (including empty = default) is multi-select
_SINGLE_SELECT_MODES = {"radiolist", "dropdown", "compact", "type_in"}


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


def _scale(tab_val: int, pbi_dim: int) -> int:
    return round((tab_val / 100000) * pbi_dim)


def _resolve_field_entity(field_name: str, transformed: dict) -> str:
    """Return PBI table name for a field, searching transformed tables then visuals."""
    for table in transformed.get("tables", []):
        for col in table.get("columns", []):
            if col.get("name") == field_name:
                return table["name"]
    for v in transformed.get("visuals", []):
        for f in v.get("row_fields", []) + v.get("col_fields", []):
            fname = f.get("name", "") if isinstance(f, dict) else str(f)
            if fname == field_name and v.get("table"):
                return v["table"]
    return ""


def _find_visual_for_sheet(sheet_name: str, transformed: dict) -> dict | None:
    """Return first visual dict from transformed output matching the sheet page name."""
    for v in transformed.get("visuals", []):
        if v.get("page_name") == sheet_name or v.get("name") == sheet_name:
            return v
    return None


def transform_dashboards(
    dashboards: list[dict],
    workbook: dict,
    transformed: dict,
) -> list[dict]:
    """Convert dashboard dicts into PBI page dicts with positioned visuals."""
    pages = []
    for dash in dashboards:
        visuals: list[dict] = []
        unsupported: list[str] = []
        visual_idx = 0

        for zone in dash["zones"]:
            visual_id = f"dash_visual_{visual_idx + 1}"
            px = _scale(zone["x"], _PBI_W)
            py = _scale(zone["y"], _PBI_H)
            pw = _scale(zone["w"], _PBI_W)
            ph = _scale(zone["h"], _PBI_H)

            if zone["zone_type"] == "sheet":
                source = _find_visual_for_sheet(zone["name"], transformed)
                if source is None:
                    continue
                visuals.append({
                    "visual_id": visual_id,
                    "visual_type": "chart",
                    "x": px, "y": py, "width": pw, "height": ph,
                    "source_sheet": zone["name"],
                    "mark_type": source["mark_type"],
                    "table": source["table"],
                    "row_fields": source.get("row_fields", []),
                    "col_fields": source.get("col_fields", []),
                    "show_data_labels": source.get("show_data_labels", False),
                    "visual_format": source.get("visual_format", {}),
                    "col_formats": source.get("col_formats", {}),
                    "sorts": source.get("sorts", []),
                    "title": source.get("title"),
                })
                visual_idx += 1

            elif zone["zone_type"] == "filter":
                entity = _resolve_field_entity(zone["param_field"], transformed)
                if not entity:
                    continue
                slicer: dict = {
                    "visual_id": visual_id,
                    "visual_type": "slicer",
                    "x": px, "y": py, "width": pw, "height": ph,
                    "field_entity": entity,
                    "field_property": zone["param_field"],
                    "slicer_mode": _SLICER_MODE_MAP.get(zone["mode"], "Basic"),
                    "multi_select": zone["mode"] not in _SINGLE_SELECT_MODES,
                    "scoped_to_sheet": zone["name"],
                }
                if zone.get("filter_policy_sheets"):
                    slicer["filter_policy_sheets"] = zone["filter_policy_sheets"]
                visuals.append(slicer)
                visual_idx += 1

            elif zone["zone_type"] in ("text", "title"):
                visuals.append({
                    "visual_id": visual_id,
                    "visual_type": "textbox",
                    "x": px, "y": py, "width": pw, "height": ph,
                    "text": zone["text"],
                })
                visual_idx += 1

        chart_visuals = [v for v in visuals if v["visual_type"] == "chart"]
        slicer_visuals = [v for v in visuals if v["visual_type"] == "slicer"]
        # NoFilter only when an explicit <filter-policy> scope restriction was parsed.
        # Tableau's default is "all worksheets using this data source" — no restriction.
        interactions = [
            {"source": s["visual_id"], "target": c["visual_id"], "type": "NoFilter"}
            for s in slicer_visuals
            for c in chart_visuals
            if s.get("filter_policy_sheets") and c["source_sheet"] not in s["filter_policy_sheets"]
        ]

        pages.append({
            "page_name": f"Dashboard_{dash['name'].replace(' ', '_')}",
            "display_name": dash["title"],
            "width": _PBI_W,
            "height": _PBI_H,
            "visuals": visuals,
            "visual_interactions": interactions,
            "unsupported": unsupported,
        })
    return pages


def write_dashboard_pages(
    dashboard_pages: list[dict],
    output_dir: Path,
    stem: str,
) -> list[dict]:
    """Write dashboard pages to PBIR output. Returns migration report entries."""
    if not dashboard_pages:
        return []

    report_dir = output_dir / f"{stem}.Report"
    pages_dir = report_dir / "definition" / "pages"
    report_entries = []
    new_section_ids = []

    for i, page in enumerate(dashboard_pages):
        section_id = f"DashboardSection{i + 1}"
        new_section_ids.append(section_id)
        page_dir = pages_dir / section_id
        page_dir.mkdir(exist_ok=True)

        _write_dashboard_page_json(page_dir, page)

        for visual in page["visuals"]:
            visual_dir = page_dir / "visuals" / visual["visual_id"]
            visual_dir.mkdir(parents=True, exist_ok=True)
            _write_dashboard_visual_json(visual_dir, visual)

        sheets_placed = [v["source_sheet"] for v in page["visuals"] if v["visual_type"] == "chart"]
        slicers_placed = [v["field_property"] for v in page["visuals"] if v["visual_type"] == "slicer"]
        report_entries.append({
            "name": page["display_name"],
            "status": "migrated" if not page.get("unsupported") else "partial",
            "sheets_placed": sheets_placed,
            "slicers_placed": slicers_placed,
            "unsupported": page.get("unsupported", []),
        })

    _update_pages_manifest(pages_dir, new_section_ids)
    return report_entries


def _write_dashboard_page_json(page_dir: Path, page: dict) -> None:
    content: dict = {
        "$schema": f"{_SCHEMA_BASE}/definition/page/2.1.0/schema.json",
        "name": page_dir.name,
        "displayName": page["display_name"],
        "displayOption": "FitToPage",
        "height": page["height"],
        "width": page["width"],
    }
    if page.get("visual_interactions"):
        content["visualInteractions"] = page["visual_interactions"]
    (page_dir / "page.json").write_text(json.dumps(content, indent=2))


def _write_dashboard_visual_json(visual_dir: Path, visual: dict) -> None:
    if visual["visual_type"] == "chart":
        content = _build_chart_visual(visual_dir.name, visual)
    elif visual["visual_type"] == "slicer":
        content = _build_slicer_visual(visual_dir.name, visual)
    else:
        content = _build_textbox_visual(visual_dir.name, visual)
    (visual_dir / "visual.json").write_text(json.dumps(content, indent=2))


def _update_pages_manifest(pages_dir: Path, new_section_ids: list[str]) -> None:
    pages_json = pages_dir / "pages.json"
    content = json.loads(pages_json.read_text())
    content["pageOrder"].extend(new_section_ids)
    pages_json.write_text(json.dumps(content, indent=2))


def _base_container(name: str, visual: dict) -> dict:
    return {
        "$schema": f"{_SCHEMA_BASE}/definition/visualContainer/1.0.0/schema.json",
        "name": name,
        "position": {
            "x": visual["x"],
            "y": visual["y"],
            "z": 0,
            "width": visual["width"],
            "height": visual["height"],
        },
    }


def _build_chart_visual(name: str, visual: dict) -> dict:
    visual_type = MARK_TO_VISUAL.get(visual["mark_type"], "tableEx")
    table = visual["table"]
    row_fields = visual.get("row_fields", [])
    col_fields = visual.get("col_fields", [])

    if visual_type in _VISUAL_ROLES:
        cat_role, val_role, cat_shelf, val_shelf = _VISUAL_ROLES[visual_type]
        cat_fields = row_fields if cat_shelf == "row" else col_fields
        val_fields = col_fields if val_shelf == "col" else row_fields
        query_state = {
            cat_role: {"projections": [_make_projection(table, f) for f in cat_fields]},
            val_role: {"projections": [_make_projection(table, f) for f in val_fields]},
        }
    else:
        all_fields = row_fields + [f for f in col_fields if f not in row_fields]
        query_state = {
            "Values": {"projections": [_make_projection(table, f) for f in all_fields]}
        }

    container = _base_container(name, visual)
    visual_obj: dict = {"visualType": visual_type, "query": {"queryState": query_state}}
    objects = _build_objects(visual, visual_type)
    if objects:
        visual_obj["objects"] = objects
    title_info = visual.get("title")
    if title_info:
        visual_obj["visualContainerObjects"] = _build_title_objects(title_info)
    container["visual"] = visual_obj
    return container


def _build_slicer_visual(name: str, visual: dict) -> dict:
    projection = {
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": visual["field_entity"]}},
                "Property": visual["field_property"],
            }
        },
        "queryRef": f"{visual['field_entity']}.{visual['field_property']}",
        "active": True,
    }
    objects: dict = {
        "data": [{"properties": {
            "mode": {"expr": {"Literal": {"Value": f"'{visual['slicer_mode']}'"}}},
        }}],
    }
    if visual["slicer_mode"] != "Between" and visual.get("multi_select", False):
        objects["selection"] = [{"properties": {
            "singleSelect": {"expr": {"Literal": {"Value": "false"}}},
            "strictSingleSelect": {"expr": {"Literal": {"Value": "false"}}},
            "selectAllCheckboxEnabled": {"expr": {"Literal": {"Value": "true"}}},
        }}]
    container = _base_container(name, visual)
    container["visual"] = {
        "visualType": "slicer",
        "query": {"queryState": {"Values": {"projections": [projection]}}},
        "objects": objects,
        "drillFilterOtherVisuals": True,
    }
    return container


def _build_textbox_visual(name: str, visual: dict) -> dict:
    container = _base_container(name, visual)
    container["visual"] = {
        "visualType": "textbox",
        "objects": {
            "general": [{"properties": {
                "paragraphs": [{"textRuns": [{"value": visual["text"]}]}]
            }}]
        },
    }
    return container
