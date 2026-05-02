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


def test_simple_join_twb_no_filters():
    workbook = parse(SIMPLE_JOIN)
    for sheet in workbook["sheets"]:
        assert sheet["filters"] == []


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


def test_transformer_simple_join_report_no_sheet_filters():
    transformed = transform(parse(SIMPLE_JOIN))
    assert transformed["report"]["sheet_filters"] == []
