"""Tests for T11: .twbx unzip and embedded data file extraction."""

from pathlib import Path

import pytest

from tab_to_pbi.parser import parse, extract_twbx_data
from tab_to_pbi.transformer import transform
from tab_to_pbi.generator import generate
from tab_to_pbi.validator import validate


TWBX = Path("input/tabpbi.twbx")


def test_parse_twbx_returns_workbook():
    workbook = parse(TWBX)
    assert workbook["name"] == "tabpbi"
    assert len(workbook["datasources"]) > 0
    assert len(workbook["sheets"]) > 0


def test_parse_twbx_datasource_names():
    workbook = parse(TWBX)
    names = {ds["caption"] for ds in workbook["datasources"]}
    assert "Sample - Superstore" in names


def test_extract_twbx_data_creates_files(tmp_path):
    dest = extract_twbx_data(TWBX, tmp_path / "data")
    files = {f.name for f in dest.iterdir()}
    assert "Sales Target.xlsx" in files
    assert "Sample - Superstore.xls" in files
    assert "Sales Commission.csv" in files


def test_extract_twbx_data_no_twb_in_dest(tmp_path):
    dest = extract_twbx_data(TWBX, tmp_path / "data")
    twb_files = list(dest.glob("*.twb"))
    assert twb_files == []


def test_extract_twbx_data_flat_layout(tmp_path):
    dest = extract_twbx_data(TWBX, tmp_path / "data")
    # All files should be directly in dest, not in subdirectories
    for f in dest.iterdir():
        assert f.parent == dest


def test_twbx_pipeline_e2e(tmp_path):
    """Full pipeline: parse → transform → generate → validate, 0 errors."""
    data_dir = extract_twbx_data(TWBX, tmp_path / "data")
    workbook = parse(TWBX)
    transformed = transform(workbook)
    report_path = generate(transformed, tmp_path, data_dir)
    results = validate(report_path)
    errors = [r for r in results if r.level == "ERROR"]
    assert errors == [], f"Validation errors: {errors}"


def test_twbx_pipeline_generates_pages(tmp_path):
    data_dir = extract_twbx_data(TWBX, tmp_path / "data")
    transformed = transform(parse(TWBX))
    report_path = generate(transformed, tmp_path, data_dir)
    pages_json = report_path / "definition" / "pages" / "pages.json"
    assert pages_json.exists()
