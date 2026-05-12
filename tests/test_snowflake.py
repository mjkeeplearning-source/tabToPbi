"""Snowflake connector: M expression generation tests."""

from pathlib import Path
from unittest.mock import patch

import pytest

from tab_to_pbi.generator import _build_m_expression


def _conn(overrides: dict) -> dict:
    base = {
        "type": "snowflake",
        "server": "acct.snowflakecomputing.com",
        "warehouse": "MY_WH",
        "dbname": "MY_DB",
        "schema": "MY_SCHEMA",
        "table": "MY_TABLE",
        "custom_sql": "",
        "storage_mode": "directQuery",
        "filename": "",
    }
    return {**base, **overrides}


DATA_DIR = Path("output")


# ---------------------------------------------------------------------------
# Standard table navigation
# ---------------------------------------------------------------------------

def test_snowflake_uses_warehouse_as_second_arg():
    lines, _ = _build_m_expression(_conn({}), DATA_DIR)
    source_line = next(l for l in lines if "Snowflake.Databases" in l)
    assert '"MY_WH"' in source_line
    assert '"MY_DB"' not in source_line


def test_snowflake_includes_implementation_option():
    lines, _ = _build_m_expression(_conn({}), DATA_DIR)
    source_line = next(l for l in lines if "Snowflake.Databases" in l)
    assert 'Implementation="2.0"' in source_line


def test_snowflake_three_level_navigation():
    lines, _ = _build_m_expression(_conn({}), DATA_DIR)
    joined = "\n".join(lines)
    assert 'Kind="Database"' in joined
    assert 'Kind="Schema"' in joined
    assert 'Kind="Table"' in joined
    assert '"MY_DB"' in joined
    assert '"MY_SCHEMA"' in joined
    assert '"MY_TABLE"' in joined


def test_snowflake_no_warehouse_still_connects():
    lines, _ = _build_m_expression(_conn({"warehouse": ""}), DATA_DIR)
    source_line = next(l for l in lines if "Snowflake.Databases" in l)
    assert 'Implementation="2.0"' in source_line


def test_snowflake_does_not_use_schema_item_navigation():
    """The generic PostgreSQL-style nav must NOT be used for Snowflake."""
    lines, _ = _build_m_expression(_conn({}), DATA_DIR)
    joined = "\n".join(lines)
    assert "Schema=" not in joined
    assert "Item=" not in joined


# ---------------------------------------------------------------------------
# DirectQuery + date-part columns → NativeQuery
# ---------------------------------------------------------------------------

def test_snowflake_date_part_uses_warehouse_in_source():
    dpc = [{"base_col": "ORDER_DATE", "part": "YEAR", "derived": "ORDER_DATE Year"}]
    lines, _ = _build_m_expression(_conn({}), DATA_DIR, date_part_columns=dpc)
    source_line = next(l for l in lines if "Snowflake.Databases" in l)
    assert '"MY_WH"' in source_line


def test_snowflake_date_part_alias_is_double_escaped():
    """Column alias in NativeQuery SQL must use ANSI "" escaping inside M string."""
    dpc = [{"base_col": "ORDER_DATE", "part": "YEAR", "derived": "ORDER_DATE Year"}]
    lines, _ = _build_m_expression(_conn({}), DATA_DIR, date_part_columns=dpc)
    native_line = next(l for l in lines if "NativeQuery" in l)
    # The alias must appear as ""ORDER_DATE Year"" (double-escaped for M string literal)
    assert '""ORDER_DATE Year""' in native_line


def test_snowflake_date_part_sql_uses_year_function():
    dpc = [{"base_col": "ORDER_DATE", "part": "YEAR", "derived": "ORDER_DATE Year"}]
    lines, _ = _build_m_expression(_conn({}), DATA_DIR, date_part_columns=dpc)
    native_line = next(l for l in lines if "NativeQuery" in l)
    assert "YEAR(ORDER_DATE)" in native_line


# ---------------------------------------------------------------------------
# Custom SQL → NativeQuery
# ---------------------------------------------------------------------------

def test_snowflake_custom_sql_uses_warehouse():
    conn = _conn({"custom_sql": "SELECT * FROM MY_SCHEMA.MY_TABLE"})
    lines, use_backtick = _build_m_expression(conn, DATA_DIR)
    source_line = next(l for l in lines if "Snowflake.Databases" in l)
    assert '"MY_WH"' in source_line
    assert use_backtick is True


# ---------------------------------------------------------------------------
# End-to-end: snowflkake.twb produces 0 pipeline errors
# ---------------------------------------------------------------------------

def test_snowflake_e2e_zero_errors():
    from tab_to_pbi.parser import parse
    from tab_to_pbi.transformer import transform
    from tab_to_pbi.generator import generate
    from tab_to_pbi.validator import validate

    twb = Path("input/snowflkake.twb")
    if not twb.exists():
        pytest.skip("snowflkake.twb not present")

    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        workbook = parse(twb)
        transformed = transform(workbook)
        generate(transformed, out, Path(tmp))
        report_dir = next(out.glob("*.Report"))
        results = validate(report_dir)
        errors = [r for r in results if r.level == "ERROR"]
        assert errors == []
