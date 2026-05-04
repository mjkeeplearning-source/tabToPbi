"""Tests for sorting migration: Tableau sort elements → PBI sortDefinition."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tab_to_pbi.parser import parse, _parse_sorts
from tab_to_pbi.transformer import transform, _enrich_sorts
from tab_to_pbi.generator import _build_sort_definition

import xml.etree.ElementTree as ET


SIMPLE_SORTED = Path("input/simple_sorted.twb")


# --- Parser ---

def test_sorted_workbook_sheets_have_sorts():
    workbook = parse(SIMPLE_SORTED)
    sheets_with_sorts = [s for s in workbook["sheets"] if s.get("sorts")]
    assert len(sheets_with_sorts) > 0


def test_computed_sort_parsed():
    workbook = parse(SIMPLE_SORTED)
    computed = [
        s for sheet in workbook["sheets"]
        for s in sheet.get("sorts", [])
        if s["type"] == "computed"
    ]
    assert len(computed) > 0
    s = computed[0]
    assert s["field"] == "category"
    assert s["direction"] == "DESC"
    assert "using" in s
    assert "using_prefix" in s


def test_natural_sort_parsed():
    workbook = parse(SIMPLE_SORTED)
    natural = [
        s for sheet in workbook["sheets"]
        for s in sheet.get("sorts", [])
        if s["type"] == "natural"
    ]
    assert len(natural) > 0
    s = natural[0]
    assert s["field"] == "category"
    assert s["direction"] == "DESC"
    assert "using" not in s


def test_alphabetic_sort_parsed():
    workbook = parse(SIMPLE_SORTED)
    alpha = [
        s for sheet in workbook["sheets"]
        for s in sheet.get("sorts", [])
        if s["type"] == "alphabetic"
    ]
    assert len(alpha) > 0
    s = alpha[0]
    assert s["field"] == "sub_category"
    assert s["direction"] == "ASC"


def test_unsorted_sheet_has_empty_sorts():
    workbook = parse(Path("input/simple.twb"))
    for sheet in workbook["sheets"]:
        assert sheet.get("sorts", []) == []


# --- Parser helper: multiple sorts on one sheet ---

def test_sheet3_has_two_sorts():
    """Sheet 3 has both natural-sort and alphabetic-sort on different columns."""
    workbook = parse(SIMPLE_SORTED)
    sheet3 = next(s for s in workbook["sheets"] if s["name"] == "Sheet 3")
    assert len(sheet3["sorts"]) == 2
    types = {s["type"] for s in sheet3["sorts"]}
    assert types == {"natural", "alphabetic"}


# --- _enrich_sorts ---

def test_enrich_natural_sort():
    sorts = [{"type": "natural", "field": "category", "direction": "DESC"}]
    fmap = {"category": "orders"}
    enriched, warnings = _enrich_sorts(sorts, fmap, {}, "orders")
    assert len(enriched) == 1
    assert warnings == []
    s = enriched[0]
    assert s["sort_field"] == "category"
    assert s["sort_table"] == "orders"
    assert s["direction"] == "DESC"
    assert s["is_measure"] is False


def test_enrich_alphabetic_sort():
    sorts = [{"type": "alphabetic", "field": "sub_category", "direction": "ASC"}]
    enriched, warnings = _enrich_sorts(sorts, {"sub_category": "orders"}, {}, "orders")
    assert len(enriched) == 1
    assert enriched[0]["is_measure"] is False
    assert enriched[0]["sort_field"] == "sub_category"
    assert enriched[0]["direction"] == "ASC"


def test_enrich_computed_sort_with_calc_field():
    sorts = [{"type": "computed", "field": "category", "direction": "DESC",
              "using": "Calculation_123", "using_prefix": "usr"}]
    cmap = {"Calculation_123": "DeltaOrder"}
    fmap = {"category": "orders", "DeltaOrder": "orders"}
    enriched, warnings = _enrich_sorts(sorts, fmap, cmap, "orders")
    assert len(enriched) == 1
    assert warnings == []
    s = enriched[0]
    assert s["sort_field"] == "DeltaOrder"
    assert s["sort_table"] == "orders"
    assert s["is_measure"] is True
    assert s["direction"] == "DESC"


def test_enrich_computed_sort_unknown_calc_skipped():
    sorts = [{"type": "computed", "field": "category", "direction": "DESC",
              "using": "Calculation_unknown", "using_prefix": "usr"}]
    enriched, warnings = _enrich_sorts(sorts, {}, {}, "orders")
    assert enriched == []
    assert len(warnings) == 1
    assert "unknown calc field" in warnings[0]


def test_enrich_manual_sort_skipped():
    sorts = [{"type": "manual", "field": "category", "direction": "ASC"}]
    enriched, warnings = _enrich_sorts(sorts, {}, {}, "orders")
    assert enriched == []
    assert len(warnings) == 1
    assert "Manual sort" in warnings[0]


def test_enrich_multiple_sorts():
    sorts = [
        {"type": "natural", "field": "category", "direction": "DESC"},
        {"type": "alphabetic", "field": "sub_category", "direction": "ASC"},
    ]
    fmap = {"category": "orders", "sub_category": "orders"}
    enriched, warnings = _enrich_sorts(sorts, fmap, {}, "orders")
    assert len(enriched) == 2
    assert warnings == []


# --- _build_sort_definition ---

def test_build_sort_definition_none_when_empty():
    assert _build_sort_definition([]) is None


def test_build_sort_definition_column_ascending():
    sorts = [{"sort_field": "category", "sort_table": "orders", "direction": "ASC", "is_measure": False}]
    result = _build_sort_definition(sorts)
    assert result is not None
    assert result["isDefaultSort"] is False
    item = result["sort"][0]
    assert item["direction"] == "Ascending"
    assert "Column" in item["field"]
    assert item["field"]["Column"]["Property"] == "category"
    assert item["field"]["Column"]["Expression"]["SourceRef"]["Entity"] == "orders"


def test_build_sort_definition_measure_descending():
    sorts = [{"sort_field": "DeltaOrder", "sort_table": "orders", "direction": "DESC", "is_measure": True}]
    result = _build_sort_definition(sorts)
    item = result["sort"][0]
    assert item["direction"] == "Descending"
    assert "Measure" in item["field"]
    assert item["field"]["Measure"]["Property"] == "DeltaOrder"


def test_build_sort_definition_multiple_items():
    sorts = [
        {"sort_field": "category", "sort_table": "orders", "direction": "DESC", "is_measure": False},
        {"sort_field": "sub_category", "sort_table": "orders", "direction": "ASC", "is_measure": False},
    ]
    result = _build_sort_definition(sorts)
    assert len(result["sort"]) == 2


# --- Integration: transform produces sorts on visuals ---

def test_transform_passes_sorts_to_visuals():
    workbook = parse(SIMPLE_SORTED)
    transformed = transform(workbook)
    visuals_with_sorts = [v for v in transformed["visuals"] if v.get("sorts")]
    assert len(visuals_with_sorts) > 0


# --- Integration: generator writes sortDefinition to visual.json ---

def test_generator_writes_sort_definition(tmp_path):
    """End-to-end: simple_sorted.twb produces visual.json with sortDefinition."""
    from tab_to_pbi.generator import generate

    workbook = parse(SIMPLE_SORTED)
    transformed = transform(workbook)

    # Mock Claude translation so no API calls needed
    with patch("tab_to_pbi.translator.translate_calc_fields_in_transformed") as mock_translate:
        mock_translate.side_effect = lambda t: t  # pass-through
        generate(transformed, tmp_path)

    # Find any visual.json and check for sortDefinition
    visual_jsons = list(tmp_path.rglob("visual.json"))
    assert len(visual_jsons) > 0

    visuals_with_sort = []
    for vj in visual_jsons:
        data = json.loads(vj.read_text())
        query = data.get("visual", {}).get("query", {})
        if "sortDefinition" in query:
            visuals_with_sort.append(vj)

    assert len(visuals_with_sort) > 0, "No visual.json has sortDefinition"


def test_sort_definition_schema_valid(tmp_path):
    """sortDefinition in visual.json must have correct field structure per MS schema."""
    from tab_to_pbi.generator import generate

    workbook = parse(SIMPLE_SORTED)
    transformed = transform(workbook)

    with patch("tab_to_pbi.translator.translate_calc_fields_in_transformed") as mock_translate:
        mock_translate.side_effect = lambda t: t
        generate(transformed, tmp_path)

    for vj in tmp_path.rglob("visual.json"):
        data = json.loads(vj.read_text())
        sort_def = data.get("visual", {}).get("query", {}).get("sortDefinition")
        if sort_def is None:
            continue
        assert "sort" in sort_def
        assert isinstance(sort_def["sort"], list)
        assert "isDefaultSort" in sort_def
        for item in sort_def["sort"]:
            assert "field" in item
            assert "direction" in item
            assert item["direction"] in ("Ascending", "Descending")
            field = item["field"]
            assert "Column" in field or "Measure" in field
            expr_key = "Column" if "Column" in field else "Measure"
            assert "Expression" in field[expr_key]
            assert "Property" in field[expr_key]
