"""Tests for PBIR validator."""
import json
from pathlib import Path
import pytest
from tab_to_pbi.validator import ValidationResult, load_schema


def test_validation_result_fields():
    r = ValidationResult(level="ERROR", file="foo/bar.json", message="missing field")
    assert r.level == "ERROR"
    assert r.file == "foo/bar.json"
    assert r.message == "missing field"


def test_load_schema_returns_dict(tmp_path):
    url = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
    cache_dir = tmp_path / ".pbir_schema_cache"
    schema = load_schema(url, cache_dir)
    assert isinstance(schema, dict)
    assert "$schema" in schema or "properties" in schema


def test_load_schema_uses_cache(tmp_path):
    url = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
    cache_dir = tmp_path / ".pbir_schema_cache"
    schema1 = load_schema(url, cache_dir)
    schema2 = load_schema(url, cache_dir)
    assert schema1 == schema2
    assert any(cache_dir.iterdir())
