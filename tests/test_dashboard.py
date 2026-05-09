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


def test_transform_visual_interactions_nofilter():
    """Slicer scoped to Sheet1 must NoFilter all charts that are NOT Sheet1."""
    dashboards = [{
        "name": "TestDash", "width": 1000, "height": 620, "title": "Test",
        "zones": [
            {
                "zone_type": "sheet", "name": "Sheet1",
                "x": 0, "y": 0, "w": 50000, "h": 100000,
            },
            {
                "zone_type": "sheet", "name": "Sheet2",
                "x": 50000, "y": 0, "w": 50000, "h": 100000,
            },
            {
                "zone_type": "filter", "name": "Sheet1",
                "param_field": "Region",
                "param_datasource_id": "federated.abc",
                "mode": "dropdown",
                "x": 0, "y": 0, "w": 10000, "h": 10000,
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
        "visuals": [
            {"name": "Sheet1", "page_name": "Sheet1", "mark_type": "Bar",
             "table": "orders", "row_fields": [], "col_fields": []},
            {"name": "Sheet2", "page_name": "Sheet2", "mark_type": "Bar",
             "table": "orders", "row_fields": [], "col_fields": []},
        ]
    }
    pages = transform_dashboards(dashboards, workbook, transformed)
    interactions = pages[0]["visual_interactions"]
    # slicer (dash_visual_3) should NoFilter Sheet2 chart (dash_visual_2) only
    assert len(interactions) == 1
    assert interactions[0]["source"] == "dash_visual_3"
    assert interactions[0]["target"] == "dash_visual_2"
    assert interactions[0]["type"] == "NoFilter"


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
        "visuals": [
            {"name": "Sheet1", "page_name": "Sheet1", "mark_type": "Bar",
             "table": "orders", "row_fields": [], "col_fields": []},
        ]
    }
    pages = transform_dashboards(dashboards, workbook, transformed)
    assert pages[0]["visual_interactions"] == []
