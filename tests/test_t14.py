"""T14: Tableau → PBI visual type mapping (deterministic rules)."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from tab_to_pbi.parser import _parse_sheets
from tab_to_pbi.transformer import transform, _infer_mark_type
from tab_to_pbi.generator import MARK_TO_VISUAL


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
