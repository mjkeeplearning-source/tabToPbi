"""Tests for Tableau worksheet title migration to PBI visual titles."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from tab_to_pbi.parser import _parse_title
from tab_to_pbi.transformer import _resolve_title


def _ws(title_xml: str) -> ET.Element:
    """Build a minimal worksheet XML element with a custom title."""
    xml = f"""<worksheet name="Test Sheet">
  <layout-options>
    <title>
      <formatted-text>
        {title_xml}
      </formatted-text>
    </title>
  </layout-options>
</worksheet>"""
    return ET.fromstring(xml)


def _ws_no_title() -> ET.Element:
    return ET.fromstring('<worksheet name="Test Sheet"></worksheet>')


# ---------------------------------------------------------------------------
# _parse_title: structured runs
# ---------------------------------------------------------------------------

def test_no_title_returns_none():
    assert _parse_title(_ws_no_title()) is None


def test_static_title_returns_text_run():
    ws = _ws('<run>Product Wise Quality</run>')
    result = _parse_title(ws)
    assert result is not None
    assert result["runs"] == [{"kind": "text", "value": "Product Wise Quality"}]


def test_sheet_name_token_parsed_as_token_run():
    ws = _ws('<run>&lt;Sheet Name&gt;</run>')
    result = _parse_title(ws)
    assert result is not None
    assert result["runs"] == [{"kind": "token", "token": "sheet_name"}]


def test_workbook_name_token_parsed_as_token_run():
    ws = _ws('<run>&lt;Workbook Name&gt;</run>')
    result = _parse_title(ws)
    assert result is not None
    assert result["runs"] == [{"kind": "token", "token": "workbook_name"}]


def test_page_name_token_parsed_as_token_run():
    ws = _ws('<run>&lt;Page Name&gt;</run>')
    result = _parse_title(ws)
    assert result is not None
    assert result["runs"] == [{"kind": "token", "token": "page_name"}]


def test_field_ref_token_parsed_as_field_ref_run():
    ws = _ws('<run><![CDATA[<[federated.xxx].[yr:Order Date:ok]>]]></run>')
    result = _parse_title(ws)
    assert result is not None
    assert len(result["runs"]) >= 1
    assert any(r["kind"] == "field_ref" for r in result["runs"])


def test_formatting_captured_from_styled_run():
    ws = _ws('<run fontsize="14" bold="true" fontcolor="#4e79a7">My Title</run>')
    result = _parse_title(ws)
    assert result["formatting"]["font_size"] == 14
    assert result["formatting"]["bold"] is True
    assert result["formatting"]["font_color"] == "#4e79a7"


def test_mixed_static_and_token_runs():
    ws = _ws('<run>Report: </run><run>&lt;Sheet Name&gt;</run>')
    result = _parse_title(ws)
    runs = result["runs"]
    assert runs[0] == {"kind": "text", "value": "Report: "}
    assert runs[1] == {"kind": "token", "token": "sheet_name"}


# ---------------------------------------------------------------------------
# _resolve_title: token resolution
# ---------------------------------------------------------------------------

def _title_with_runs(runs: list) -> dict:
    return {"runs": runs, "formatting": {}}


def test_resolve_static_text_unchanged():
    title_info = _title_with_runs([{"kind": "text", "value": "Product Wise Quality"}])
    result = _resolve_title(title_info, "Product Performance", "MyWorkbook")
    assert result["text"] == "Product Wise Quality"


def test_resolve_sheet_name_token():
    title_info = _title_with_runs([{"kind": "token", "token": "sheet_name"}])
    result = _resolve_title(title_info, "Product Performance", "MyWorkbook")
    assert result["text"] == "Product Performance"


def test_resolve_workbook_name_token():
    title_info = _title_with_runs([{"kind": "token", "token": "workbook_name"}])
    result = _resolve_title(title_info, "My Sheet", "daatabricks")
    assert result["text"] == "daatabricks"


def test_resolve_unresolvable_token_falls_back_to_sheet_name():
    title_info = _title_with_runs([{"kind": "token", "token": "page_name"}])
    result = _resolve_title(title_info, "Sales Transaction", "MyWorkbook")
    assert result["text"] == "Sales Transaction"


def test_resolve_field_ref_falls_back_to_sheet_name():
    title_info = _title_with_runs([{"kind": "field_ref", "value": "<[ds].[yr:Date:ok]>"}])
    result = _resolve_title(title_info, "Sales Transaction", "MyWorkbook")
    assert result["text"] == "Sales Transaction"


def test_resolve_mixed_static_and_sheet_name():
    title_info = _title_with_runs([
        {"kind": "text", "value": "Report: "},
        {"kind": "token", "token": "sheet_name"},
    ])
    result = _resolve_title(title_info, "Product Performance", "MyWorkbook")
    assert result["text"] == "Report: Product Performance"


def test_resolve_preserves_formatting():
    title_info = {"runs": [{"kind": "text", "value": "My Title"}], "formatting": {"font_size": 14, "bold": True}}
    result = _resolve_title(title_info, "My Sheet", "wb")
    assert result["font_size"] == 14
    assert result["bold"] is True


def test_resolve_none_falls_back_to_sheet_name():
    result = _resolve_title(None, "My Sheet", "wb")
    assert result == {"text": "My Sheet"}


# ---------------------------------------------------------------------------
# End-to-end: daatabricks.twb sheets with <Sheet Name> title
# ---------------------------------------------------------------------------

def test_daatabricks_titles_resolve_to_sheet_names():
    """Sheets using <Sheet Name> token must get the actual sheet name as title."""
    from tab_to_pbi.parser import parse
    from tab_to_pbi.transformer import transform

    twb_path = Path("input/daatabricks.twb")
    if not twb_path.exists():
        pytest.skip("daatabricks.twb not available")

    workbook = parse(twb_path)
    transformed = transform(workbook, workbook_name="daatabricks")

    visuals = transformed["visuals"]
    # Find sheets that had <Sheet Name> token — their visual title should match the sheet name
    sheet_name_token_sheets = {"Product Performance", "Sales  Transaction"}
    for v in visuals:
        if v["page_name"] in sheet_name_token_sheets:
            title = v.get("title")
            assert title is not None, f"Sheet '{v['page_name']}' should have a title"
            assert title["text"] == v["page_name"], (
                f"Sheet '{v['page_name']}' title should be '{v['page_name']}', got '{title['text']}'"
            )
