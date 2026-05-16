"""T14: Tableau → PBI visual type mapping (deterministic rules)."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from tab_to_pbi.parser import _parse_sheets
from tab_to_pbi.transformer import transform, _infer_mark_type
from tab_to_pbi.generator import MARK_TO_VISUAL, generate


# ---------------------------------------------------------------------------
# MARK_TO_VISUAL completeness
# ---------------------------------------------------------------------------

def test_high_confidence_mappings_present():
    assert MARK_TO_VISUAL["Bar"] == "barChart"
    assert MARK_TO_VISUAL["Line"] == "lineChart"
    assert MARK_TO_VISUAL["Area"] == "areaChart"
    assert MARK_TO_VISUAL["Pie"] == "pieChart"
    assert MARK_TO_VISUAL["Text"] == "tableEx"


def test_medium_confidence_mappings_present():
    assert MARK_TO_VISUAL["Circle"] == "scatterChart"
    assert MARK_TO_VISUAL["Shape"] == "scatterChart"
    assert MARK_TO_VISUAL["Polygon"] == "filledMap"
    assert MARK_TO_VISUAL["Multipolygon"] == "filledMap"
    assert MARK_TO_VISUAL["PolyLine"] == "map"


def test_unknown_mark_falls_back_to_tableEx():
    assert MARK_TO_VISUAL.get("GanttBar", "tableEx") == "tableEx"
    assert MARK_TO_VISUAL.get("Heatmap", "tableEx") == "tableEx"
    assert MARK_TO_VISUAL.get("VizExtension", "tableEx") == "tableEx"


# ---------------------------------------------------------------------------
# mark_orientation wires Bar → columnChart
# ---------------------------------------------------------------------------

def _make_workbook(mark_type: str, mark_orientation: str = "") -> dict:
    return {
        "name": "test",
        "datasources": [{
            "name": "ds1",
            "caption": "DS1",
            "connection": {"type": "excel-direct", "filename": "f.xlsx", "table": "T",
                           "table_name": "T", "server": "", "dbname": "", "port": "",
                           "username": "", "custom_sql": "", "live_connection": False},
            "tables": [{"name": "T", "schema": "", "table": "T"}],
            "columns": [{"name": "Cat", "datatype": "string", "source_table": "T"},
                        {"name": "Val", "datatype": "real", "source_table": "T"}],
            "calculated_fields": [],
            "calc_name_map": {},
            "relationships": [],
        }],
        "sheets": [{
            "name": "Sheet1",
            "datasource": "ds1",
            "rows": [{"name": "Cat", "continuous": False, "aggregation": None}],
            "cols": [{"name": "Val", "continuous": True, "aggregation": "SUM"}],
            "mark_type": mark_type,
            "mark_orientation": mark_orientation,
            "filters": [],
        }],
        "unsupported": [],
    }


def test_bar_no_orientation_maps_to_barChart():
    transformed = transform(_make_workbook("Bar", ""))
    assert transformed["visuals"][0]["mark_type"] == "Bar"


def test_bar_orientation_y_maps_to_column():
    transformed = transform(_make_workbook("Bar", "y"))
    assert transformed["visuals"][0]["mark_type"] == "Column"


def test_bar_orientation_x_stays_bar():
    transformed = transform(_make_workbook("Bar", "x"))
    assert transformed["visuals"][0]["mark_type"] == "Bar"


# ---------------------------------------------------------------------------
# Degraded mark types emit unsupported warning
# ---------------------------------------------------------------------------

def test_heatmap_emits_unsupported_warning():
    wb = _make_workbook("Heatmap")
    transformed = transform(wb)
    warnings = transformed["report"]["unsupported"]
    assert any("Heatmap" in w for w in warnings)
    assert any("rendered as table" in w for w in warnings)


def test_ganttbar_emits_unsupported_warning():
    wb = _make_workbook("GanttBar")
    transformed = transform(wb)
    assert any("GanttBar" in w for w in transformed["report"]["unsupported"])


def test_vizextension_emits_unsupported_warning():
    wb = _make_workbook("VizExtension")
    transformed = transform(wb)
    assert any("VizExtension" in w for w in transformed["report"]["unsupported"])


def test_supported_mark_no_warning():
    """Pie is supported — no unsupported warning should be added."""
    wb = _make_workbook("Pie")
    transformed = transform(wb)
    visual_warnings = [w for w in transformed["report"]["unsupported"] if "rendered as table" in w]
    assert visual_warnings == []


# ---------------------------------------------------------------------------
# Automatic shelf inference (regression)
# ---------------------------------------------------------------------------

def test_infer_bar_from_shelves():
    rows = [{"name": "Cat", "continuous": False, "aggregation": None}]
    cols = [{"name": "Val", "continuous": True, "aggregation": "SUM"}]
    assert _infer_mark_type(rows, cols) == "Bar"


def test_infer_column_from_shelves():
    rows = [{"name": "Val", "continuous": True, "aggregation": "SUM"}]
    cols = [{"name": "Cat", "continuous": False, "aggregation": None}]
    assert _infer_mark_type(rows, cols) == "Column"


def test_infer_line_from_shelves():
    rows = [{"name": "Val", "continuous": True, "aggregation": "SUM"}]
    cols = [{"name": "Date", "continuous": True, "aggregation": None}]
    assert _infer_mark_type(rows, cols) == "Line"


def test_infer_line_from_ordinal_date_on_cols():
    """Discrete (ordinal) date part on cols + measure on rows → Line, matching Tableau Automatic behavior."""
    rows = [{"name": "sales", "continuous": True, "aggregation": "SUM", "date_part": None}]
    cols = [{"name": "order_date", "continuous": False, "aggregation": None, "date_part": "YEAR"}]
    assert _infer_mark_type(rows, cols) == "Line"


def test_infer_table_from_shelves():
    rows = [{"name": "Cat", "continuous": False, "aggregation": None}]
    cols = [{"name": "Sub", "continuous": False, "aggregation": None}]
    assert _infer_mark_type(rows, cols) == "Automatic"


# ---------------------------------------------------------------------------
# Pie chart: text encoding fallback when no wedge-size encoding present
# ---------------------------------------------------------------------------

_DS = "federated.test"

def _make_pie_root(color_col: str, wedge_col: str | None, text_col: str | None) -> ET.Element:
    """Build a minimal workbook root with one Pie worksheet.

    Column attributes use the Tableau [ds].[field] bracket format.
    """
    enc_parts = [f'<color column="[{_DS}].[{color_col}]" />']
    if wedge_col:
        enc_parts.append(f'<wedge-size column="[{_DS}].[{wedge_col}]" />')
    if text_col:
        enc_parts.append(f'<text column="[{_DS}].[{text_col}]" />')
    encodings = "\n".join(enc_parts)
    xml = f"""<workbook>
      <worksheets>
        <worksheet name="PieSheet">
          <table>
            <view>
              <datasource-dependencies datasource="{_DS}" />
            </view>
            <panes>
              <pane>
                <mark class="Pie" />
                <encodings>{encodings}</encodings>
              </pane>
            </panes>
            <rows />
            <cols />
          </table>
        </worksheet>
      </worksheets>
    </workbook>"""
    return ET.fromstring(xml)


def test_pie_wedge_encoding_populates_cols():
    """Pie chart with explicit <wedge-size> puts the measure in col_fields."""
    root = _make_pie_root(
        color_col="none:Category:nk",
        wedge_col="sum:Sales:qk",
        text_col=None,
    )
    sheets = _parse_sheets(root)
    assert sheets[0]["mark_type"] == "Pie"
    assert len(sheets[0]["cols"]) == 1
    assert sheets[0]["cols"][0]["name"] == "Sales"
    assert sheets[0]["cols"][0]["aggregation"] == "SUM"


def test_pie_text_encoding_fallback_populates_cols_when_no_wedge():
    """Pie chart with only <text> encoding (no <wedge-size>) must fall back
    to text_enc_fields so the PBI Y role gets a projection and slices render."""
    root = _make_pie_root(
        color_col="none:Category:nk",
        wedge_col=None,
        text_col="cnt:Orders:qk",
    )
    sheets = _parse_sheets(root)
    assert sheets[0]["mark_type"] == "Pie"
    assert len(sheets[0]["cols"]) == 1, "col_fields must not be empty — Y role needs a measure"
    assert sheets[0]["cols"][0]["name"] == "Orders"
    assert sheets[0]["cols"][0]["aggregation"] == "COUNTA"


def test_pie_no_encodings_keeps_cols_empty():
    """Pie chart with no measure encoding leaves col_fields empty — nothing to fall back to."""
    root = _make_pie_root(
        color_col="none:Category:nk",
        wedge_col=None,
        text_col=None,
    )
    sheets = _parse_sheets(root)
    assert sheets[0]["mark_type"] == "Pie"
    assert sheets[0]["cols"] == []


def test_pie_text_fallback_on_actual_workbook():
    """Sales Profit Pie Chart in the dashboard workbook must have non-empty col_fields
    so the PBI pieChart Y role gets a projection."""
    from tab_to_pbi.parser import parse
    wb = parse(Path("input/simple_join_calculated_line_dashboard_multiple_visual.twb"))
    pie_sheet = next(s for s in wb["sheets"] if s["name"] == "Sales  Profit Pie Chart")
    assert pie_sheet["mark_type"] == "Pie"
    assert len(pie_sheet["cols"]) > 0, (
        "Pie chart col_fields is empty — Y role will have no projections in PBI"
    )


# ---------------------------------------------------------------------------
# Stacked area chart: Area mark + color dimension → stackedAreaChart
# ---------------------------------------------------------------------------

def _make_area_workbook_with_series() -> dict:
    """Minimal workbook: Area mark with a dimension on the color/series shelf."""
    return {
        "name": "test",
        "datasources": [{
            "name": "ds1",
            "caption": "DS1",
            "connection": {
                "type": "excel-direct", "filename": "f.xlsx", "table": "T",
                "table_name": "T", "server": "", "dbname": "", "port": "",
                "username": "", "custom_sql": "", "live_connection": False,
            },
            "tables": [{"name": "T", "schema": "", "table": "T"}],
            "columns": [
                {"name": "Product", "datatype": "string", "source_table": "T"},
                {"name": "Quantity", "datatype": "integer", "source_table": "T"},
                {"name": "Country", "datatype": "string", "source_table": "T"},
            ],
            "calculated_fields": [],
            "calc_name_map": {},
            "relationships": [],
        }],
        "sheets": [{
            "name": "Area Chart",
            "datasource": "ds1",
            "cols": [{"name": "Product", "continuous": False, "aggregation": None}],
            "rows": [{"name": "Quantity", "continuous": True, "aggregation": "SUM"}],
            "mark_type": "Area",
            "mark_orientation": "",
            "filters": [],
            "encoding_fields": [{"name": "Country", "continuous": False, "aggregation": None}],
        }],
        "unsupported": [],
        "datasource_filters": [],
    }


def _first_visual_json(report_path: Path) -> dict:
    """Return parsed content of the first visual.json found under report_path."""
    visual_files = sorted(report_path.rglob("visual.json"))
    assert visual_files, f"No visual.json found under {report_path}"
    return json.loads(visual_files[0].read_text(encoding="utf-8"))


def test_area_with_series_generates_stacked_area_chart(tmp_path):
    """Area mark + color dimension → visualType must be stackedAreaChart.

    Tableau stacks areas automatically when a dimension is on the Color shelf.
    PBI equivalent is stackedAreaChart, not the non-stacked areaChart.
    Ground truth: PBI Desktop 2.152 visual.json for a manually created stacked
    area chart uses visualType='stackedAreaChart' with Category/Y/Series roles.
    """
    transformed = transform(_make_area_workbook_with_series())
    report_path = generate(transformed, tmp_path, Path("."))
    visual = _first_visual_json(report_path)
    assert visual["visual"]["visualType"] == "stackedAreaChart"


def test_area_without_series_generates_plain_area_chart(tmp_path):
    """Area mark with no color dimension → visualType must stay areaChart (non-stacked)."""
    wb = _make_workbook("Area")
    transformed = transform(wb)
    report_path = generate(transformed, tmp_path, Path("."))
    visual = _first_visual_json(report_path)
    assert visual["visual"]["visualType"] == "areaChart"


def test_stacked_area_chart_has_category_y_series_roles(tmp_path):
    """stackedAreaChart visual must have Category, Y, and Series roles.

    Confirmed from PBI Desktop 2.152 ground truth visual.json.
    """
    transformed = transform(_make_area_workbook_with_series())
    report_path = generate(transformed, tmp_path, Path("."))
    visual = _first_visual_json(report_path)
    query_state = visual["visual"]["query"]["queryState"]
    assert "Category" in query_state
    assert "Y" in query_state
    assert "Series" in query_state


def test_daatabricks_area_chart_on_dashboard_generates_stacked_area_chart(tmp_path):
    """Area Chart placed on Sales Dashboard must also be stackedAreaChart.

    The dashboard code path (_build_chart_visual in dashboard.py) is separate
    from the sheet code path (_write_visual in generator.py).  Both must apply
    the areaChart → stackedAreaChart upgrade when color_fields is non-empty.
    """
    from unittest.mock import patch
    from tab_to_pbi.parser import parse
    from tab_to_pbi.translator import translate_calc_fields_in_transformed
    from tab_to_pbi.dashboard import (
        parse_dashboards_from_path,
        transform_dashboards,
        write_dashboard_pages,
    )

    workbook = parse(Path("input/daatabricks.twb"))
    transformed = transform(workbook)
    with patch("tab_to_pbi.translator.translate_calc_fields_in_transformed", return_value=transformed):
        transformed = translate_calc_fields_in_transformed(transformed)
    generate(transformed, tmp_path, Path("data"))

    dashboards = parse_dashboards_from_path(Path("input/daatabricks.twb"))
    dashboard_pages = transform_dashboards(dashboards, workbook, transformed)
    write_dashboard_pages(dashboard_pages, tmp_path, "daatabricks")

    report_path = tmp_path / "daatabricks.Report"
    visual_files = list(report_path.rglob("visual.json"))
    # Find the Area Chart visual in DashboardSection1
    dash_area_visual = None
    for p in visual_files:
        if p.parent.parent.parent.name == "DashboardSection1":
            content = json.loads(p.read_text(encoding="utf-8"))
            if content.get("visual", {}).get("visualType") in ("areaChart", "stackedAreaChart"):
                dash_area_visual = content
                break
    assert dash_area_visual is not None, "No area/stackedArea visual found in DashboardSection1"
    assert dash_area_visual["visual"]["visualType"] == "stackedAreaChart", (
        f"Expected stackedAreaChart on dashboard, got {dash_area_visual['visual']['visualType']}"
    )


def test_daatabricks_area_chart_generates_stacked_area_chart(tmp_path):
    """Area Chart sheet in daatabricks.twb has country on color → stackedAreaChart.

    This is the real-world workbook that exposed the bug.
    """
    from unittest.mock import patch
    from tab_to_pbi.parser import parse
    from tab_to_pbi.translator import translate_calc_fields_in_transformed

    workbook = parse(Path("input/daatabricks.twb"))
    transformed = transform(workbook)
    with patch("tab_to_pbi.translator.translate_calc_fields_in_transformed", return_value=transformed):
        transformed = translate_calc_fields_in_transformed(transformed)
    report_path = generate(transformed, tmp_path, Path("data"))

    # Area Chart is the first sheet → ReportSection1
    # path: <report>/definition/pages/ReportSection1/visuals/<id>/visual.json
    # p.parent = <id>/, p.parent.parent = visuals/, p.parent.parent.parent = ReportSection1/
    visual_files = {
        p.parent.parent.parent.name: json.loads(p.read_text(encoding="utf-8"))
        for p in report_path.rglob("visual.json")
        if p.parent.parent.parent.name.startswith("ReportSection")
    }
    area_visual = visual_files.get("ReportSection1")
    assert area_visual is not None, f"ReportSection1 visual not found. Sections: {list(visual_files)}"
    assert area_visual["visual"]["visualType"] == "stackedAreaChart"
