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
