"""Tests for T10: worksheet filter extraction."""

from pathlib import Path

import pytest

from tab_to_pbi.parser import parse
from tab_to_pbi.transformer import transform


SUPERSTORE = Path("input/Superstore.twb")
SIMPLE = Path("input/simple.twb")
SIMPLE_JOIN = Path("input/simple_join.twb")


# --- Parser: filter extraction ---

def test_superstore_sheets_have_filters():
    workbook = parse(SUPERSTORE)
    sheets_with_filters = [s for s in workbook["sheets"] if s["filters"]]
    assert len(sheets_with_filters) > 0


def test_filter_has_required_keys():
    workbook = parse(SUPERSTORE)
    for sheet in workbook["sheets"]:
        for f in sheet["filters"]:
            assert "field" in f
            assert "class" in f


def test_categorical_filter_no_min_max():
    workbook = parse(SUPERSTORE)
    for sheet in workbook["sheets"]:
        for f in sheet["filters"]:
            if f["class"] == "categorical":
                assert "min" not in f
                assert "max" not in f


def test_quantitative_filter_has_min_max():
    workbook = parse(SUPERSTORE)
    quantitative = [
        f for s in workbook["sheets"] for f in s["filters"] if f["class"] == "quantitative"
    ]
    assert len(quantitative) > 0
    for f in quantitative:
        assert "min" in f
        assert "max" in f


def test_virtual_fields_excluded_from_filters():
    workbook = parse(SUPERSTORE)
    for sheet in workbook["sheets"]:
        for f in sheet["filters"]:
            assert not f["field"].startswith(":")


def test_simple_join_sheet1_quantitative_filter():
    workbook = parse(SIMPLE_JOIN)
    sheet1 = next(s for s in workbook["sheets"] if s["name"] == "Sheet 1")
    assert len(sheet1["filters"]) == 1
    f = sheet1["filters"][0]
    assert f["class"] == "quantitative"
    assert f["field"] == "profit"
    assert f["agg_prefix"] == "max"
    assert f["min"] == "1013.13"
    assert "max" in f


def test_simple_join_sheet2_categorical_filter_has_values():
    workbook = parse(SIMPLE_JOIN)
    sheet2 = next(s for s in workbook["sheets"] if s["name"] == "Sheet 2")
    assert len(sheet2["filters"]) == 1
    f = sheet2["filters"][0]
    assert f["class"] == "categorical"
    assert f["field"] == "sub_category"
    assert "values" in f
    assert "Accessories" in f["values"]


def test_simple_join_datasource_filters():
    workbook = parse(SIMPLE_JOIN)
    ds_filters = workbook["datasource_filters"]
    assert len(ds_filters) == 1
    assert ds_filters[0]["field"] == "region"
    assert ds_filters[0]["class"] == "categorical"
    assert set(ds_filters[0]["values"]) == {"East", "South", "West"}


def test_simple_join_sheet3_rows_has_category_and_subcategory():
    workbook = parse(SIMPLE_JOIN)
    sheet3 = next(s for s in workbook["sheets"] if s["name"] == "Sheet 3")
    row_names = [f["name"] for f in sheet3["rows"]]
    assert "category" in row_names
    assert "sub_category" in row_names


# --- Transformer: filters passed to visuals and report ---

def test_transformer_visuals_have_filters():
    transformed = transform(parse(SUPERSTORE))
    for visual in transformed["visuals"]:
        assert "filters" in visual


def test_transformer_report_has_sheet_filters():
    transformed = transform(parse(SUPERSTORE))
    assert "sheet_filters" in transformed["report"]
    assert len(transformed["report"]["sheet_filters"]) > 0


def test_transformer_sheet_filters_structure():
    transformed = transform(parse(SUPERSTORE))
    for entry in transformed["report"]["sheet_filters"]:
        assert "sheet" in entry
        assert "filters" in entry
        assert isinstance(entry["filters"], list)


def test_transformer_simple_join_report_has_sheet_filters():
    transformed = transform(parse(SIMPLE_JOIN))
    sheet_filters = transformed["report"]["sheet_filters"]
    assert len(sheet_filters) >= 1
    sheet_names = [sf["sheet"] for sf in sheet_filters]
    assert "Sheet 1" in sheet_names


def test_transformer_enriches_visual_filters_with_table():
    transformed = transform(parse(SIMPLE_JOIN))
    sheet1_visual = next(v for v in transformed["visuals"] if v["page_name"] == "Sheet 1")
    for f in sheet1_visual["filters"]:
        assert "table" in f
        assert f["table"] != ""


def test_transformer_datasource_filters_enriched():
    transformed = transform(parse(SIMPLE_JOIN))
    ds_filters = transformed["datasource_filters"]
    assert len(ds_filters) == 1
    assert ds_filters[0]["field"] == "region"
    assert ds_filters[0]["table"] == "orders"
