"""End-to-end pipeline tests for T9 (calc field extraction) and T13 (DAX translation)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tab_to_pbi.parser import parse
from tab_to_pbi.transformer import transform
from tab_to_pbi.translator import translate_calc_fields_in_transformed
from tab_to_pbi.generator import generate
from tab_to_pbi.validator import validate

SIMPLE = Path("input/simple.twb")
SIMPLE_JOIN = Path("input/simple_join.twb")
SUPERSTORE = Path("input/Superstore.twb")


def _mock_translate(formula: str, table_name: str, columns=None, directquery: bool = False, all_tables=None) -> tuple[str, str]:
    """Deterministic stand-in for Claude: translate simple formulas, reject Parameters/cross-ds."""
    if any(marker in formula for marker in ("[Parameters].", "[federated.", "INDEX()")):
        return ("", "unsupported")
    return (f"MOCK_DAX({table_name})", "translated")


# ---------------------------------------------------------------------------
# T9 end-to-end: parse → transform → generate → validate
# (no translation — calc fields stay pending_translation)
# ---------------------------------------------------------------------------

def test_t9_simple_join_report_has_two_pending_fields(tmp_path):
    transformed = transform(parse(SIMPLE_JOIN))
    cfs = transformed["report"]["calculated_fields"]
    assert len(cfs) == 2
    assert all(cf["status"] == "pending_translation" for cf in cfs)
    assert {cf["name"] for cf in cfs} == {"DeltaOrder", "Margin"}


def test_t9_superstore_report_has_pending_fields(tmp_path):
    transformed = transform(parse(SUPERSTORE))
    cfs = transformed["report"]["calculated_fields"]
    assert len(cfs) == 21
    assert all(cf["status"] == "pending_translation" for cf in cfs)


def test_t9_pending_fields_carry_table(tmp_path):
    """Each pending calc field must reference its primary table."""
    transformed = transform(parse(SUPERSTORE))
    for cf in transformed["report"]["calculated_fields"]:
        assert cf.get("table"), f"calc field '{cf['name']}' has no table"


def test_t9_pending_fields_not_in_tmdl(tmp_path):
    """Calc fields pending translation must not appear as TMDL measures."""
    transformed = transform(parse(SIMPLE_JOIN))
    generate(transformed, tmp_path, Path("data"))
    for tmdl in (tmp_path / "simple_join.SemanticModel/definition/tables").glob("*.tmdl"):
        assert "Calculation_" not in tmdl.read_text()


def test_t9_simple_join_passes_validation(tmp_path):
    transformed = transform(parse(SIMPLE_JOIN))
    report_path = generate(transformed, tmp_path, Path("data"))
    errors = [r for r in validate(report_path) if r.level == "ERROR"]
    assert errors == []


def test_t9_superstore_passes_validation(tmp_path):
    transformed = transform(parse(SUPERSTORE))
    report_path = generate(transformed, tmp_path, Path("data"))
    errors = [r for r in validate(report_path) if r.level == "ERROR"]
    assert errors == []


def test_t9_simple_twb_no_calc_fields(tmp_path):
    transformed = transform(parse(SIMPLE))
    report_path = generate(transformed, tmp_path, Path("data"))
    assert transformed["report"]["calculated_fields"] == []
    errors = [r for r in validate(report_path) if r.level == "ERROR"]
    assert errors == []


# ---------------------------------------------------------------------------
# T13 end-to-end: full pipeline with mocked translation
# ---------------------------------------------------------------------------

def test_t13_translated_fields_change_status():
    transformed = transform(parse(SIMPLE_JOIN))
    with patch("tab_to_pbi.translator.translate_formula", side_effect=_mock_translate):
        result = translate_calc_fields_in_transformed(transformed)
    for cf in result["report"]["calculated_fields"]:
        assert cf["status"] in ("translated", "unsupported")
        assert cf["status"] != "pending_translation"


def test_t13_translated_fields_have_dax():
    transformed = transform(parse(SIMPLE_JOIN))
    with patch("tab_to_pbi.translator.translate_formula", side_effect=_mock_translate):
        result = translate_calc_fields_in_transformed(transformed)
    for cf in result["report"]["calculated_fields"]:
        if cf["status"] == "translated":
            assert cf.get("dax"), f"translated field '{cf['name']}' has no dax"


def test_t13_unsupported_fields_have_no_dax():
    transformed = transform(parse(SUPERSTORE))
    with patch("tab_to_pbi.translator.translate_formula", side_effect=_mock_translate):
        result = translate_calc_fields_in_transformed(transformed)
    for cf in result["report"]["calculated_fields"]:
        if cf["status"] == "unsupported":
            assert not cf.get("dax"), f"unsupported field '{cf['name']}' has dax"


def test_t13_translated_measures_in_tmdl(tmp_path):
    transformed = transform(parse(SIMPLE_JOIN))
    with patch("tab_to_pbi.translator.translate_formula", side_effect=_mock_translate):
        result = translate_calc_fields_in_transformed(transformed)
    generate(result, tmp_path, Path("data"))
    all_tmdl = list((tmp_path / "simple_join.SemanticModel/definition/tables").glob("*.tmdl"))
    all_content = "\n".join(t.read_text() for t in all_tmdl)
    translated_names = [cf["name"] for cf in result["report"]["calculated_fields"] if cf["status"] == "translated"]
    for name in translated_names:
        assert name in all_content, f"translated measure '{name}' not found in any TMDL"


def test_t13_unsupported_measures_not_in_tmdl(tmp_path):
    transformed = transform(parse(SUPERSTORE))
    with patch("tab_to_pbi.translator.translate_formula", side_effect=_mock_translate):
        result = translate_calc_fields_in_transformed(transformed)
    generate(result, tmp_path, Path("data"))
    unsupported_names = [cf["name"] for cf in result["report"]["calculated_fields"] if cf["status"] == "unsupported"]
    for tmdl in (tmp_path / "Superstore.SemanticModel/definition/tables").glob("*.tmdl"):
        content = tmdl.read_text()
        for name in unsupported_names:
            assert f"measure '{name}'" not in content, f"unsupported '{name}' found in {tmdl.name}"


def test_t13_no_translation_called_for_simple_twb():
    """simple.twb has no calc fields — translate_formula must not be called."""
    transformed = transform(parse(SIMPLE))
    with patch("tab_to_pbi.translator.translate_formula") as mock_fn:
        result = translate_calc_fields_in_transformed(transformed)
        mock_fn.assert_not_called()
    assert result["report"]["calculated_fields"] == []


def test_t13_superstore_passes_validation_after_translation(tmp_path):
    transformed = transform(parse(SUPERSTORE))
    with patch("tab_to_pbi.translator.translate_formula", side_effect=_mock_translate):
        result = translate_calc_fields_in_transformed(transformed)
    report_path = generate(result, tmp_path, Path("data"))
    errors = [r for r in validate(report_path) if r.level == "ERROR"]
    assert errors == []


def test_t13_translated_measures_added_to_measures_list():
    """Translated calc fields must appear in transformed['measures']."""
    transformed = transform(parse(SIMPLE_JOIN))
    before_count = len(transformed["measures"])
    with patch("tab_to_pbi.translator.translate_formula", side_effect=_mock_translate):
        result = translate_calc_fields_in_transformed(transformed)
    translated_count = sum(1 for cf in result["report"]["calculated_fields"] if cf["status"] == "translated")
    assert len(result["measures"]) == before_count + translated_count
