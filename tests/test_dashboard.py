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
