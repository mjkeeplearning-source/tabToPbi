"""Tests for T9: calculated field extraction and pipeline handling."""

import json
from pathlib import Path

import pytest

from tab_to_pbi.parser import parse
from tab_to_pbi.transformer import transform


SIMPLE_JOIN = Path("input/simple_join.twb")
SIMPLE = Path("input/simple.twb")


# --- Parser tests ---

def test_calc_fields_extracted():
    workbook = parse(SIMPLE_JOIN)
    ds = workbook["datasources"][0]
    assert len(ds["calculated_fields"]) == 2


def test_calc_field_names():
    workbook = parse(SIMPLE_JOIN)
    names = {cf["name"] for cf in workbook["datasources"][0]["calculated_fields"]}
    assert names == {"DeltaOrder", "Margin"}


def test_calc_field_internal_names():
    workbook = parse(SIMPLE_JOIN)
    internals = {cf["internal_name"] for cf in workbook["datasources"][0]["calculated_fields"]}
    assert all(n.startswith("Calculation_") for n in internals)


def test_calc_field_formulas():
    workbook = parse(SIMPLE_JOIN)
    by_name = {cf["name"]: cf for cf in workbook["datasources"][0]["calculated_fields"]}
    assert "COUNTD" in by_name["DeltaOrder"]["formula"]
    assert "profit" in by_name["Margin"]["formula"].lower()


def test_calc_field_datatype_and_role():
    workbook = parse(SIMPLE_JOIN)
    by_name = {cf["name"]: cf for cf in workbook["datasources"][0]["calculated_fields"]}
    assert by_name["DeltaOrder"]["datatype"] == "integer"
    assert by_name["DeltaOrder"]["role"] == "measure"
    assert by_name["Margin"]["datatype"] == "real"
    assert by_name["Margin"]["role"] == "measure"


def test_calc_name_map_built():
    workbook = parse(SIMPLE_JOIN)
    cmap = workbook["datasources"][0]["calc_name_map"]
    # keys are internal names, values are display names
    assert "DeltaOrder" in cmap.values()
    assert "Margin" in cmap.values()
    for k in cmap:
        assert k.startswith("Calculation_")


def test_no_calc_fields_for_simple_twb():
    workbook = parse(SIMPLE)
    ds = workbook["datasources"][0]
    assert ds["calculated_fields"] == []
    assert ds["calc_name_map"] == {}


# --- Transformer tests ---

def test_calc_fields_in_migration_report():
    workbook = parse(SIMPLE_JOIN)
    transformed = transform(workbook)
    report_fields = transformed["report"]["calculated_fields"]
    assert len(report_fields) == 2
    by_name = {cf["name"]: cf for cf in report_fields}
    assert "DeltaOrder" in by_name
    assert "Margin" in by_name


def test_calc_fields_status_pending():
    workbook = parse(SIMPLE_JOIN)
    transformed = transform(workbook)
    for cf in transformed["report"]["calculated_fields"]:
        assert cf["status"] == "pending_translation"


def test_calc_fields_preserve_internal_name_in_report():
    workbook = parse(SIMPLE_JOIN)
    transformed = transform(workbook)
    for cf in transformed["report"]["calculated_fields"]:
        assert cf["internal_name"].startswith("Calculation_")


def test_calc_field_refs_skipped_from_projections():
    """Shelf fields that resolve to pending calc fields must not appear in visual projections."""
    workbook = parse(SIMPLE_JOIN)
    transformed = transform(workbook)
    # Both sheets use a calc field on one shelf — verify no Calculation_xxx in projections
    for visual in transformed["visuals"]:
        all_fields = visual["row_fields"] + visual["col_fields"]
        names = [f["name"] for f in all_fields]
        assert not any(n.startswith("Calculation_") for n in names), (
            f"Visual '{visual['name']}' has raw Calculation_ ref in projections: {names}"
        )


def test_empty_report_for_simple_twb():
    workbook = parse(SIMPLE)
    transformed = transform(workbook)
    assert transformed["report"]["calculated_fields"] == []


def test_tables_generated_in_report():
    workbook = parse(SIMPLE_JOIN)
    transformed = transform(workbook)
    assert set(transformed["report"]["tables_generated"]) == {"orders", "returns"}
