import xml.etree.ElementTree as ET
from pathlib import Path
from tab_to_pbi.dashboard import parse_dashboards, parse_dashboards_from_path

TWB = Path("input/Superstore.twb")


def test_parse_dashboards_count():
    root = ET.parse(TWB).getroot()
    dashboards = parse_dashboards(root)
    assert len(dashboards) == 6


def test_parse_dashboard_names():
    root = ET.parse(TWB).getroot()
    names = [d["name"] for d in parse_dashboards(root)]
    assert "Overview" in names
    assert "Shipping" in names
    assert "Customers" in names


def test_parse_dashboard_size():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    assert shipping["width"] == 1000
    assert shipping["height"] == 620


def test_parse_dashboard_title():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    assert shipping["title"] == "On-Time Shipment Trends"


def test_parse_dashboards_from_path():
    dashboards = parse_dashboards_from_path(TWB)
    assert len(dashboards) == 6


def test_shipping_sheet_zones():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    sheet_zones = [z for z in shipping["zones"] if z["zone_type"] == "sheet"]
    names = {z["name"] for z in sheet_zones}
    assert "ShippingTrend" in names
    assert "ShipSummary" in names
    assert "DaystoShip" in names
    assert len(sheet_zones) == 3


def test_shipping_filter_zones():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    filter_zones = [z for z in shipping["zones"] if z["zone_type"] == "filter"]
    assert len(filter_zones) == 4
    fields = {z["param_field"] for z in filter_zones}
    assert "Region" in fields
    assert "Ship Mode" in fields
    assert "Order Date" in fields


def test_filter_zone_scoped_to_sheet():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    filter_zones = [z for z in shipping["zones"] if z["zone_type"] == "filter"]
    assert all(z["name"] == "ShippingTrend" for z in filter_zones)


def test_filter_zone_mode_mapping_checkdropdown():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    region_filter = next(
        z for z in shipping["zones"]
        if z["zone_type"] == "filter" and z["param_field"] == "Region"
    )
    assert region_filter["mode"] == "checkdropdown"
    assert region_filter["param_datasource_id"] == "federated.10nnk8d1vgmw8q17yu76u06pnbcj"


def test_shipping_title_zone():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    title_zones = [z for z in shipping["zones"] if z["zone_type"] == "title"]
    assert len(title_zones) == 1
    assert title_zones[0]["text"] == "On-Time Shipment Trends"


def test_paramctrl_zones_excluded():
    root = ET.parse(TWB).getroot()
    commission = next(d for d in parse_dashboards(root) if d["name"] == "Commission Model")
    zone_types = {z["zone_type"] for z in commission["zones"]}
    assert "paramctrl" not in zone_types


def test_sheet_zone_has_coordinates():
    root = ET.parse(TWB).getroot()
    shipping = next(d for d in parse_dashboards(root) if d["name"] == "Shipping")
    trend = next(z for z in shipping["zones"] if z.get("name") == "ShippingTrend")
    assert trend["x"] == 410
    assert trend["y"] == 14915
    assert trend["w"] == 86935
    assert trend["h"] == 32743


# --- Task 3: transform_dashboards() ---

from tab_to_pbi.dashboard import transform_dashboards


def _make_workbook_stub():
    return {
        "datasources": [{
            "name": "federated.abc",
            "columns": [
                {"name": "Region", "source_table": "orders"},
                {"name": "Sales", "source_table": "orders"},
            ],
        }]
    }


def _make_transformed_stub():
    return {
        "visuals": [{
            "name": "Sheet1",
            "page_name": "Sheet1",
            "mark_type": "Bar",
            "table": "orders",
            "row_fields": [{"name": "Region", "is_measure": False, "table": "orders"}],
            "col_fields": [{"name": "Sum Sales", "is_measure": True, "table": "orders"}],
        }]
    }


def test_transform_coordinate_scaling():
    dashboards = [{
        "name": "TestDash",
        "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "sheet", "name": "Sheet1",
            "x": 50000, "y": 50000, "w": 50000, "h": 50000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    assert len(pages) == 1
    v = pages[0]["visuals"][0]
    assert v["x"] == 640     # round(50000/100000 * 1280)
    assert v["y"] == 360     # round(50000/100000 * 720)
    assert v["width"] == 640
    assert v["height"] == 360


def test_transform_sheet_zone_becomes_chart_visual():
    dashboards = [{
        "name": "TestDash",
        "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "sheet", "name": "Sheet1",
            "x": 0, "y": 0, "w": 100000, "h": 100000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    v = pages[0]["visuals"][0]
    assert v["visual_type"] == "chart"
    assert v["source_sheet"] == "Sheet1"
    assert v["mark_type"] == "Bar"
    assert v["table"] == "orders"


def test_transform_unknown_sheet_skipped():
    dashboards = [{
        "name": "TestDash",
        "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "sheet", "name": "NonExistentSheet",
            "x": 0, "y": 0, "w": 50000, "h": 50000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    assert pages[0]["visuals"] == []


def test_transform_page_dimensions():
    dashboards = [{
        "name": "MyDash", "width": 1000, "height": 620, "title": "My Dashboard",
        "zones": [],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    assert pages[0]["page_name"] == "Dashboard_MyDash"
    assert pages[0]["display_name"] == "My Dashboard"
    assert pages[0]["width"] == 1280
    assert pages[0]["height"] == 720


# --- Task 4: filter zone → slicer + visual interactions ---

def test_transform_filter_zone_becomes_slicer():
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "filter", "name": "Sheet1",
            "param_field": "Region",
            "param_datasource_id": "federated.abc",
            "mode": "dropdown",
            "x": 0, "y": 0, "w": 10000, "h": 10000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    v = pages[0]["visuals"][0]
    assert v["visual_type"] == "slicer"
    assert v["field_entity"] == "orders"
    assert v["field_property"] == "Region"
    assert v["slicer_mode"] == "Dropdown"
    assert v["scoped_to_sheet"] == "Sheet1"


def test_transform_slicer_mode_radiolist():
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "filter", "name": "Sheet1",
            "param_field": "Region",
            "param_datasource_id": "federated.abc",
            "mode": "radiolist",
            "x": 0, "y": 0, "w": 10000, "h": 10000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    assert pages[0]["visuals"][0]["slicer_mode"] == "Basic"


def test_transform_filter_unresolved_field_skipped():
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "filter", "name": "Sheet1",
            "param_field": "UnknownField",
            "param_datasource_id": "federated.abc",
            "mode": "dropdown",
            "x": 0, "y": 0, "w": 10000, "h": 10000,
        }],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub())
    assert pages[0]["visuals"] == []


def test_transform_nofilter_only_when_filter_policy_present():
    """NoFilter is generated only when slicer has filter_policy_sheets restricting scope."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [
            {"zone_type": "sheet", "name": "Sheet1",
             "x": 0, "y": 0, "w": 50000, "h": 100000},
            {"zone_type": "sheet", "name": "Sheet2",
             "x": 50000, "y": 0, "w": 50000, "h": 100000},
            {"zone_type": "filter", "name": "Sheet1",
             "param_field": "Region", "param_datasource_id": "federated.abc",
             "mode": "dropdown", "x": 0, "y": 0, "w": 10000, "h": 10000,
             "filter_policy_sheets": ["Sheet1"]},  # explicit scope restriction
        ],
    }]
    workbook = {"datasources": [{"name": "federated.abc",
                                  "columns": [{"name": "Region", "source_table": "orders"}]}]}
    transformed = {
        "tables": [{"name": "orders", "columns": [{"name": "Region"}]}],
        "visuals": [
            {"name": "Sheet1", "page_name": "Sheet1", "mark_type": "Bar",
             "table": "orders", "row_fields": [], "col_fields": []},
            {"name": "Sheet2", "page_name": "Sheet2", "mark_type": "Bar",
             "table": "orders", "row_fields": [], "col_fields": []},
        ],
    }
    pages = transform_dashboards(dashboards, workbook, transformed)
    interactions = pages[0]["visual_interactions"]
    assert len(interactions) == 1
    assert interactions[0]["target"] == "dash_visual_2"  # Sheet2 is out of scope
    assert interactions[0]["type"] == "NoFilter"


def test_no_nofilter_when_sheets_differ_without_filter_policy():
    """Without explicit <filter-policy>, slicer applies to all sheets — no NoFilter interactions."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [
            {"zone_type": "sheet", "name": "Sheet1",
             "x": 0, "y": 0, "w": 50000, "h": 100000},
            {"zone_type": "sheet", "name": "Sheet2",
             "x": 50000, "y": 0, "w": 50000, "h": 100000},
            {"zone_type": "filter", "name": "Sheet1",
             "param_field": "Region", "param_datasource_id": "federated.abc",
             "mode": "dropdown", "x": 0, "y": 0, "w": 10000, "h": 10000},
        ],
    }]
    workbook = {"datasources": [{"name": "federated.abc",
                                  "columns": [{"name": "Region", "source_table": "orders"}]}]}
    transformed = {
        "tables": [{"name": "orders", "columns": [{"name": "Region"}]}],
        "visuals": [
            {"name": "Sheet1", "page_name": "Sheet1", "mark_type": "Bar",
             "table": "orders", "row_fields": [], "col_fields": []},
            {"name": "Sheet2", "page_name": "Sheet2", "mark_type": "Bar",
             "table": "orders", "row_fields": [], "col_fields": []},
        ],
    }
    pages = transform_dashboards(dashboards, workbook, transformed)
    assert pages[0]["visual_interactions"] == []


def test_transform_no_interactions_when_slicer_matches_all_charts():
    """When all charts are scoped to the same sheet as the slicer -> no interactions needed."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [
            {
                "zone_type": "sheet", "name": "Sheet1",
                "x": 0, "y": 0, "w": 100000, "h": 80000,
            },
            {
                "zone_type": "filter", "name": "Sheet1",
                "param_field": "Region",
                "param_datasource_id": "federated.abc",
                "mode": "dropdown",
                "x": 0, "y": 80000, "w": 20000, "h": 20000,
            },
        ],
    }]
    workbook = {
        "datasources": [{
            "name": "federated.abc",
            "columns": [{"name": "Region", "source_table": "orders"}],
        }]
    }
    transformed = {
        "tables": [{"name": "orders", "columns": [{"name": "Region"}]}],
        "visuals": [
            {"name": "Sheet1", "page_name": "Sheet1", "mark_type": "Bar",
             "table": "orders", "row_fields": [], "col_fields": []},
        ]
    }
    pages = transform_dashboards(dashboards, workbook, transformed)
    assert pages[0]["visual_interactions"] == []


# --- Task 5: write_dashboard_pages() ---

import json
import tempfile
from tab_to_pbi.dashboard import write_dashboard_pages


def _make_empty_pages_json(pages_dir):
    """Seed a pages.json as the existing generate() would have written it."""
    pages_dir.mkdir(parents=True, exist_ok=True)
    content = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": ["ReportSection1"],
        "activePageName": "ReportSection1",
    }
    (pages_dir / "pages.json").write_text(json.dumps(content))


def test_write_creates_page_folder():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pages_dir = tmp / "Test.Report" / "definition" / "pages"
        _make_empty_pages_json(pages_dir)

        pages = [{
            "page_name": "Dashboard_Overview", "display_name": "Overview",
            "width": 1280, "height": 720,
            "visuals": [], "visual_interactions": [], "unsupported": [],
        }]
        write_dashboard_pages(pages, tmp, "Test")
        assert (pages_dir / "DashboardSection1").is_dir()


def test_write_page_json_content():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pages_dir = tmp / "Test.Report" / "definition" / "pages"
        _make_empty_pages_json(pages_dir)

        pages = [{
            "page_name": "Dashboard_Overview", "display_name": "Overview",
            "width": 1280, "height": 720,
            "visuals": [], "visual_interactions": [], "unsupported": [],
        }]
        write_dashboard_pages(pages, tmp, "Test")
        page_json = json.loads((pages_dir / "DashboardSection1" / "page.json").read_text())
        assert page_json["displayName"] == "Overview"
        assert page_json["width"] == 1280
        assert page_json["height"] == 720
        assert page_json["displayOption"] == "FitToPage"


def test_write_page_json_with_interactions():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pages_dir = tmp / "Test.Report" / "definition" / "pages"
        _make_empty_pages_json(pages_dir)

        pages = [{
            "page_name": "Dashboard_Overview", "display_name": "Overview",
            "width": 1280, "height": 720, "unsupported": [],
            "visuals": [],
            "visual_interactions": [
                {"source": "dash_visual_2", "target": "dash_visual_3", "type": "NoFilter"}
            ],
        }]
        write_dashboard_pages(pages, tmp, "Test")
        page_json = json.loads((pages_dir / "DashboardSection1" / "page.json").read_text())
        assert "visualInteractions" in page_json
        assert page_json["visualInteractions"][0]["type"] == "NoFilter"


def test_write_updates_pages_json():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pages_dir = tmp / "Test.Report" / "definition" / "pages"
        _make_empty_pages_json(pages_dir)

        pages = [
            {
                "page_name": "Dashboard_A", "display_name": "A",
                "width": 1280, "height": 720,
                "visuals": [], "visual_interactions": [], "unsupported": [],
            },
            {
                "page_name": "Dashboard_B", "display_name": "B",
                "width": 1280, "height": 720,
                "visuals": [], "visual_interactions": [], "unsupported": [],
            },
        ]
        write_dashboard_pages(pages, tmp, "Test")
        pages_json = json.loads((pages_dir / "pages.json").read_text())
        assert "DashboardSection1" in pages_json["pageOrder"]
        assert "DashboardSection2" in pages_json["pageOrder"]
        assert "ReportSection1" in pages_json["pageOrder"]
        assert pages_json["activePageName"] == "ReportSection1"


def test_write_returns_report_entries():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pages_dir = tmp / "Test.Report" / "definition" / "pages"
        _make_empty_pages_json(pages_dir)

        pages = [{
            "page_name": "Dashboard_Overview", "display_name": "Overview",
            "width": 1280, "height": 720, "unsupported": [],
            "visuals": [
                {"visual_type": "chart", "source_sheet": "Sale Map",
                 "visual_id": "dash_visual_1", "x": 0, "y": 0, "width": 100, "height": 100,
                 "mark_type": "Bar", "table": "orders", "row_fields": [], "col_fields": []},
                {"visual_type": "slicer", "field_property": "Region",
                 "visual_id": "dash_visual_2", "x": 0, "y": 0, "width": 50, "height": 30,
                 "field_entity": "orders", "slicer_mode": "Dropdown", "scoped_to_sheet": "Sale Map"},
            ],
            "visual_interactions": [],
        }]
        result = write_dashboard_pages(pages, tmp, "Test")
        assert result[0]["name"] == "Overview"
        assert result[0]["status"] == "migrated"
        assert "Sale Map" in result[0]["sheets_placed"]
        assert "Region" in result[0]["slicers_placed"]


# --- Task 6: visual.json content tests ---

def _write_single_visual(visual_dict):
    """Helper: run write_dashboard_pages with one visual, return its visual.json content."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pages_dir = tmp / "Test.Report" / "definition" / "pages"
        _make_empty_pages_json(pages_dir)
        pages = [{
            "page_name": "Dashboard_Test", "display_name": "Test",
            "width": 1280, "height": 720,
            "visuals": [visual_dict],
            "visual_interactions": [], "unsupported": [],
        }]
        write_dashboard_pages(pages, tmp, "Test")
        visual_path = pages_dir / "DashboardSection1" / "visuals" / visual_dict["visual_id"] / "visual.json"
        return json.loads(visual_path.read_text())


def test_chart_visual_json_structure():
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "chart",
        "x": 10, "y": 20, "width": 500, "height": 300,
        "source_sheet": "Sheet1", "mark_type": "Bar", "table": "orders",
        "row_fields": [{"name": "Region", "is_measure": False, "table": "orders"}],
        "col_fields": [{"name": "Sum Sales", "is_measure": True, "table": "orders"}],
    }
    v = _write_single_visual(visual)
    assert v["name"] == "dash_visual_1"
    assert v["position"]["x"] == 10
    assert v["position"]["y"] == 20
    assert v["position"]["width"] == 500
    assert v["position"]["height"] == 300
    assert v["visual"]["visualType"] == "barChart"
    assert "Category" in v["visual"]["query"]["queryState"]
    assert "Y" in v["visual"]["query"]["queryState"]


def test_slicer_visual_json_structure():
    visual = {
        "visual_id": "dash_visual_2", "visual_type": "slicer",
        "x": 100, "y": 50, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Region",
        "slicer_mode": "Dropdown", "scoped_to_sheet": "Sheet1",
    }
    v = _write_single_visual(visual)
    assert v["visual"]["visualType"] == "slicer"
    assert v["position"]["x"] == 100
    proj = v["visual"]["query"]["queryState"]["Values"]["projections"][0]
    assert proj["field"]["Column"]["Expression"]["SourceRef"]["Entity"] == "orders"
    assert proj["field"]["Column"]["Property"] == "Region"
    mode_val = v["visual"]["objects"]["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"]
    assert mode_val == "'Dropdown'"
    assert v["visual"]["drillFilterOtherVisuals"] is True


def test_textbox_visual_json_structure():
    visual = {
        "visual_id": "dash_visual_3", "visual_type": "textbox",
        "x": 5, "y": 5, "width": 1270, "height": 30,
        "text": "Executive Overview",
    }
    v = _write_single_visual(visual)
    assert v["visual"]["visualType"] == "textbox"
    paras = v["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
    assert paras[0]["textRuns"][0]["value"] == "Executive Overview"


def test_slicer_between_mode():
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "slicer",
        "x": 0, "y": 0, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Order Date",
        "slicer_mode": "Between", "scoped_to_sheet": "ShippingTrend",
    }
    v = _write_single_visual(visual)
    mode_val = v["visual"]["objects"]["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"]
    assert mode_val == "'Between'"


# --- multi_select / singleSelect tests ---

def test_multi_select_slicer_writes_single_select_false():
    """multi_select=True must write singleSelect=false in objects.selection (not objects.data)."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "slicer",
        "x": 0, "y": 0, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Region",
        "slicer_mode": "Basic", "scoped_to_sheet": "Sheet1",
        "multi_select": True,
    }
    v = _write_single_visual(visual)
    sel_props = v["visual"]["objects"]["selection"][0]["properties"]
    assert sel_props["singleSelect"]["expr"]["Literal"]["Value"] == "false"


def test_multi_select_slicer_writes_strict_single_select_false():
    """multi_select=True must write strictSingleSelect=false so CTRL is not required."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "slicer",
        "x": 0, "y": 0, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Region",
        "slicer_mode": "Basic", "scoped_to_sheet": "Sheet1",
        "multi_select": True,
    }
    v = _write_single_visual(visual)
    sel_props = v["visual"]["objects"]["selection"][0]["properties"]
    assert sel_props["strictSingleSelect"]["expr"]["Literal"]["Value"] == "false"


def test_multi_select_slicer_writes_select_all_enabled():
    """multi_select=True must write selectAllCheckboxEnabled=true (Tableau 'All' option)."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "slicer",
        "x": 0, "y": 0, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Region",
        "slicer_mode": "Basic", "scoped_to_sheet": "Sheet1",
        "multi_select": True,
    }
    v = _write_single_visual(visual)
    sel_props = v["visual"]["objects"]["selection"][0]["properties"]
    assert sel_props["selectAllCheckboxEnabled"]["expr"]["Literal"]["Value"] == "true"


def test_multi_select_slicer_no_single_select_in_data_props():
    """singleSelect must NOT appear in objects.data.properties (wrong bucket)."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "slicer",
        "x": 0, "y": 0, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Region",
        "slicer_mode": "Basic", "scoped_to_sheet": "Sheet1",
        "multi_select": True,
    }
    v = _write_single_visual(visual)
    data_props = v["visual"]["objects"]["data"][0]["properties"]
    assert "singleSelect" not in data_props


def test_single_select_slicer_has_no_selection_object():
    """multi_select=False must NOT write objects.selection."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "slicer",
        "x": 0, "y": 0, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Region",
        "slicer_mode": "Basic", "scoped_to_sheet": "Sheet1",
        "multi_select": False,
    }
    v = _write_single_visual(visual)
    assert "selection" not in v["visual"]["objects"]


def test_between_slicer_has_no_selection_object():
    """Between (range) slicers must NOT write objects.selection."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "slicer",
        "x": 0, "y": 0, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Order Date",
        "slicer_mode": "Between", "scoped_to_sheet": "Sheet1",
        "multi_select": True,
    }
    v = _write_single_visual(visual)
    assert "selection" not in v["visual"]["objects"]


def test_single_select_slicer_omits_single_select_property():
    """multi_select=False must NOT write singleSelect in objects.data."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "slicer",
        "x": 0, "y": 0, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Region",
        "slicer_mode": "Basic", "scoped_to_sheet": "Sheet1",
        "multi_select": False,
    }
    v = _write_single_visual(visual)
    data_props = v["visual"]["objects"]["data"][0]["properties"]
    assert "singleSelect" not in data_props


def test_between_slicer_omits_single_select_property():
    """Between (range) slicers must never have singleSelect in objects.data."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "slicer",
        "x": 0, "y": 0, "width": 200, "height": 60,
        "field_entity": "orders", "field_property": "Order Date",
        "slicer_mode": "Between", "scoped_to_sheet": "Sheet1",
        "multi_select": True,
    }
    v = _write_single_visual(visual)
    data_props = v["visual"]["objects"]["data"][0]["properties"]
    assert "singleSelect" not in data_props


def test_transform_checkdropdown_sets_multi_select_true():
    """checkdropdown zone mode -> multi_select=True on the slicer dict."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "filter", "name": "Sheet1",
            "param_field": "Region", "param_datasource_id": "federated.abc",
            "mode": "checkdropdown", "x": 0, "y": 0, "w": 10000, "h": 10000,
        }],
    }]
    workbook = {"datasources": [{"name": "federated.abc",
                                  "columns": [{"name": "Region", "source_table": "orders"}]}]}
    pages = transform_dashboards(dashboards, workbook, _make_transformed_stub())
    assert pages[0]["visuals"][0]["multi_select"] is True


def test_transform_empty_mode_sets_multi_select_true():
    """Empty (absent) zone mode -> multi_select=True (Tableau implicit default is multi-select)."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "filter", "name": "Sheet1",
            "param_field": "Region", "param_datasource_id": "federated.abc",
            "mode": "", "x": 0, "y": 0, "w": 10000, "h": 10000,
        }],
    }]
    workbook = {"datasources": [{"name": "federated.abc",
                                  "columns": [{"name": "Region", "source_table": "orders"}]}]}
    pages = transform_dashboards(dashboards, workbook, _make_transformed_stub())
    assert pages[0]["visuals"][0]["multi_select"] is True


def test_transform_radiolist_sets_multi_select_false():
    """radiolist zone mode -> multi_select=False (single-select radio buttons)."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "filter", "name": "Sheet1",
            "param_field": "Region", "param_datasource_id": "federated.abc",
            "mode": "radiolist", "x": 0, "y": 0, "w": 10000, "h": 10000,
        }],
    }]
    workbook = {"datasources": [{"name": "federated.abc",
                                  "columns": [{"name": "Region", "source_table": "orders"}]}]}
    pages = transform_dashboards(dashboards, workbook, _make_transformed_stub())
    assert pages[0]["visuals"][0]["multi_select"] is False


def test_transform_dropdown_sets_multi_select_false():
    """dropdown zone mode -> multi_select=False (single-select dropdown)."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "filter", "name": "Sheet1",
            "param_field": "Region", "param_datasource_id": "federated.abc",
            "mode": "dropdown", "x": 0, "y": 0, "w": 10000, "h": 10000,
        }],
    }]
    workbook = {"datasources": [{"name": "federated.abc",
                                  "columns": [{"name": "Region", "source_table": "orders"}]}]}
    pages = transform_dashboards(dashboards, workbook, _make_transformed_stub())
    assert pages[0]["visuals"][0]["multi_select"] is False


# --- Bug 3: data labels on dashboard chart visuals ---

def _make_transformed_stub_with_labels():
    return {
        "visuals": [{
            "name": "Sheet1",
            "page_name": "Sheet1",
            "mark_type": "Bar",
            "table": "orders",
            "row_fields": [{"name": "Region", "is_measure": False, "table": "orders"}],
            "col_fields": [{"name": "Sum Sales", "is_measure": True, "table": "orders"}],
            "show_data_labels": True,
            "visual_format": {},
            "col_formats": {},
            "sorts": [],
        }]
    }


def test_transform_carries_show_data_labels():
    """show_data_labels=True on a source visual must be present in the dashboard chart dict."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{"zone_type": "sheet", "name": "Sheet1",
                   "x": 0, "y": 0, "w": 100000, "h": 100000}],
    }]
    pages = transform_dashboards(dashboards, _make_workbook_stub(), _make_transformed_stub_with_labels())
    v = pages[0]["visuals"][0]
    assert v["show_data_labels"] is True


def test_chart_visual_json_has_data_labels_when_enabled():
    """visual.json must contain objects.labels.show=true when show_data_labels=True."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "chart",
        "x": 0, "y": 0, "width": 500, "height": 300,
        "source_sheet": "Sheet1", "mark_type": "Bar", "table": "orders",
        "row_fields": [{"name": "Region", "is_measure": False, "table": "orders"}],
        "col_fields": [{"name": "Sum Sales", "is_measure": True, "table": "orders"}],
        "show_data_labels": True,
        "visual_format": {},
    }
    v = _write_single_visual(visual)
    labels = v["visual"]["objects"]["labels"]
    assert labels[0]["properties"]["show"]["expr"]["Literal"]["Value"] == "true"


def test_chart_visual_json_no_data_labels_when_disabled():
    """visual.json must NOT contain objects.labels when show_data_labels is False/absent."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "chart",
        "x": 0, "y": 0, "width": 500, "height": 300,
        "source_sheet": "Sheet1", "mark_type": "Bar", "table": "orders",
        "row_fields": [{"name": "Region", "is_measure": False, "table": "orders"}],
        "col_fields": [{"name": "Sum Sales", "is_measure": True, "table": "orders"}],
        "show_data_labels": False,
        "visual_format": {},
    }
    v = _write_single_visual(visual)
    assert "labels" not in v["visual"].get("objects", {})


def test_chart_visual_json_has_title_when_present():
    """visual.json must contain visualContainerObjects.title when source has a title."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "chart",
        "x": 0, "y": 0, "width": 500, "height": 300,
        "source_sheet": "Sheet1", "mark_type": "Bar", "table": "orders",
        "row_fields": [{"name": "Region", "is_measure": False, "table": "orders"}],
        "col_fields": [{"name": "Sum Sales", "is_measure": True, "table": "orders"}],
        "show_data_labels": False,
        "visual_format": {},
        "title": {"text": "Sales and Profit", "bold": True},
    }
    v = _write_single_visual(visual)
    vco = v["visual"]["visualContainerObjects"]
    title_props = vco["title"][0]["properties"]
    assert title_props["show"]["expr"]["Literal"]["Value"] == "true"
    assert title_props["text"]["expr"]["Literal"]["Value"] == "'Sales and Profit'"
    assert title_props["bold"]["expr"]["Literal"]["Value"] == "true"


def test_chart_visual_json_no_title_when_absent():
    """visual.json must NOT contain visualContainerObjects when title is absent."""
    visual = {
        "visual_id": "dash_visual_1", "visual_type": "chart",
        "x": 0, "y": 0, "width": 500, "height": 300,
        "source_sheet": "Sheet1", "mark_type": "Bar", "table": "orders",
        "row_fields": [{"name": "Region", "is_measure": False, "table": "orders"}],
        "col_fields": [{"name": "Sum Sales", "is_measure": True, "table": "orders"}],
        "show_data_labels": False,
        "visual_format": {},
    }
    v = _write_single_visual(visual)
    assert "visualContainerObjects" not in v["visual"]


def test_transform_copies_title_from_source_visual():
    """transform_dashboards() must carry title from the source visual into the chart dict."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [{
            "zone_type": "sheet", "name": "Sheet1",
            "x": 0, "y": 0, "w": 100000, "h": 100000,
        }],
    }]
    workbook = {"datasources": []}
    transformed = {
        "visuals": [{
            "name": "Sheet1", "page_name": "Sheet1", "mark_type": "Bar",
            "table": "orders", "row_fields": [], "col_fields": [],
            "title": {"text": "My Custom Title"},
        }]
    }
    pages = transform_dashboards(dashboards, workbook, transformed)
    chart = pages[0]["visuals"][0]
    assert chart["title"] == {"text": "My Custom Title"}
