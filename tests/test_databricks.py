"""Databricks connection type support — parser, transformer, generator."""

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

from tab_to_pbi.parser import (
    parse,
    _parse_connection,
    _parse_tables,
    _SUPPORTED_CONN_TYPES,
    _SQL_CONN_TYPES,
)
from tab_to_pbi.transformer import transform, _SQL_CONN_TYPES as TRANSFORMER_SQL_CONN_TYPES
from tab_to_pbi.generator import _build_m_expression, generate
from tab_to_pbi.validator import validate

DAATABRICKS = Path("input/daatabricks.twb")

# ---------------------------------------------------------------------------
# Minimal XML helpers
# ---------------------------------------------------------------------------

_DATABRICKS_DS_XML = """\
<datasource caption='sales_customers (samples.bakehouse.sales_customers)+ (bakehouse)'
            inline='true' name='federated.test' version='18.1'>
  <connection class='federated'>
    <named-connections>
      <named-connection caption='dbc-b0e64326-49ff.cloud.databricks.com'
                        name='databricks.test'>
        <connection authentication='oauth' class='databricks'
                     dbname='samples'
                     schema='bakehouse'
                     server='dbc-b0e64326-49ff.cloud.databricks.com'
                     v-http-path='/sql/1.0/warehouses/7691ee00ee3de572'
                     username='user@example.com' />
      </named-connection>
    </named-connections>
    <relation type='collection'>
      <relation connection='databricks.test' name='sales_customers'
                table='[samples].[bakehouse].[sales_customers]' type='table' />
      <relation connection='databricks.test' name='sales_transactions'
                table='[samples].[bakehouse].[sales_transactions]' type='table' />
    </relation>
  </connection>
</datasource>"""


def _make_ds() -> ET.Element:
    return ET.fromstring(_DATABRICKS_DS_XML)


# ---------------------------------------------------------------------------
# Parser: _SUPPORTED_CONN_TYPES and _SQL_CONN_TYPES
# ---------------------------------------------------------------------------

def test_databricks_in_supported_conn_types():
    assert "databricks" in _SUPPORTED_CONN_TYPES


def test_databricks_in_parser_sql_conn_types():
    assert "databricks" in _SQL_CONN_TYPES


# ---------------------------------------------------------------------------
# Parser: _parse_connection extracts http_path from v-http-path
# ---------------------------------------------------------------------------

def test_parse_connection_extracts_http_path():
    ds = _make_ds()
    conn = _parse_connection(ds)
    assert conn["http_path"] == "/sql/1.0/warehouses/7691ee00ee3de572"


def test_parse_connection_extracts_server_and_dbname():
    ds = _make_ds()
    conn = _parse_connection(ds)
    assert conn["server"] == "dbc-b0e64326-49ff.cloud.databricks.com"
    assert conn["dbname"] == "samples"
    assert conn["type"] == "databricks"


# ---------------------------------------------------------------------------
# Parser: _parse_tables handles 3-part [catalog].[schema].[table] names
# ---------------------------------------------------------------------------

def test_parse_tables_3part_name_schema():
    ds = _make_ds()
    conn = _parse_connection(ds)
    tables = _parse_tables(ds, conn)
    schemas = {t["name"]: t["schema"] for t in tables}
    assert schemas["sales_customers"] == "bakehouse"
    assert schemas["sales_transactions"] == "bakehouse"


def test_parse_tables_3part_name_table():
    ds = _make_ds()
    conn = _parse_connection(ds)
    tables = _parse_tables(ds, conn)
    names = {t["name"]: t["table"] for t in tables}
    assert names["sales_customers"] == "sales_customers"
    assert names["sales_transactions"] == "sales_transactions"


def test_parse_tables_3part_returns_two_tables():
    ds = _make_ds()
    conn = _parse_connection(ds)
    tables = _parse_tables(ds, conn)
    assert len(tables) == 2


# ---------------------------------------------------------------------------
# Transformer: multi-table path taken for databricks
# ---------------------------------------------------------------------------

def test_transformer_sql_conn_types_includes_databricks():
    assert "databricks" in TRANSFORMER_SQL_CONN_TYPES


def test_transform_databricks_produces_two_pbi_tables():
    """Transformer must emit one PBI table per physical Databricks table."""
    workbook = parse(DAATABRICKS)
    transformed = transform(workbook)
    table_names = [t["name"] for t in transformed["tables"]]
    assert "sales_customers" in table_names
    assert "sales_transactions" in table_names


# ---------------------------------------------------------------------------
# Generator: _build_m_expression produces DatabricksMultiCloud.Catalogs M
# ---------------------------------------------------------------------------

def _databricks_conn(table: str) -> dict:
    return {
        "type": "databricks",
        "server": "dbc-b0e64326-49ff.cloud.databricks.com",
        "http_path": "/sql/1.0/warehouses/7691ee00ee3de572",
        "dbname": "samples",
        "schema": "bakehouse",
        "table": table,
        "storage_mode": "import",
    }


def test_m_expression_uses_databricks_multicloud_function():
    lines, _ = _build_m_expression(_databricks_conn("sales_customers"), Path("."))
    expr = "\n".join(lines)
    assert "DatabricksMultiCloud.Catalogs" in expr


def test_m_expression_contains_server_and_http_path():
    lines, _ = _build_m_expression(_databricks_conn("sales_customers"), Path("."))
    expr = "\n".join(lines)
    assert "dbc-b0e64326-49ff.cloud.databricks.com" in expr
    assert "/sql/1.0/warehouses/7691ee00ee3de572" in expr


def test_m_expression_navigates_catalog():
    lines, _ = _build_m_expression(_databricks_conn("sales_customers"), Path("."))
    expr = "\n".join(lines)
    assert 'Name="samples"' in expr
    assert 'Kind="Database"' in expr


def test_m_expression_navigates_schema():
    lines, _ = _build_m_expression(_databricks_conn("sales_customers"), Path("."))
    expr = "\n".join(lines)
    assert 'Name="bakehouse"' in expr
    assert 'Kind="Schema"' in expr


def test_m_expression_navigates_table():
    lines, _ = _build_m_expression(_databricks_conn("sales_customers"), Path("."))
    expr = "\n".join(lines)
    assert 'Name="sales_customers"' in expr
    assert 'Kind="Table"' in expr


def test_m_expression_not_error_fallback():
    lines, _ = _build_m_expression(_databricks_conn("sales_customers"), Path("."))
    expr = "\n".join(lines)
    assert "error" not in expr


def test_m_expression_implementation_20():
    """PBI Desktop writes Implementation=2.0 (ADBC driver) — match that."""
    lines, _ = _build_m_expression(_databricks_conn("sales_customers"), Path("."))
    expr = "\n".join(lines)
    assert 'Implementation="2.0"' in expr


# ---------------------------------------------------------------------------
# E2E: full pipeline on daatabricks.twb
# ---------------------------------------------------------------------------

def test_e2e_databricks_no_pipeline_errors(tmp_path):
    """Full pipeline must produce 0 validator errors for daatabricks.twb."""
    from tab_to_pbi.translator import translate_calc_fields_in_transformed

    workbook = parse(DAATABRICKS)
    transformed = transform(workbook)
    with patch("tab_to_pbi.translator.translate_calc_fields_in_transformed", return_value=transformed):
        transformed = translate_calc_fields_in_transformed(transformed)
    report_path = generate(transformed, tmp_path, Path("data"))
    results = validate(report_path)
    errors = [r for r in results if r.level == "ERROR"]
    assert errors == [], f"Validator errors: {errors}"


def test_e2e_databricks_tmdl_contains_multicloud(tmp_path):
    """Generated TMDL must use DatabricksMultiCloud.Catalogs, not error fallback."""
    from tab_to_pbi.translator import translate_calc_fields_in_transformed

    workbook = parse(DAATABRICKS)
    transformed = transform(workbook)
    with patch("tab_to_pbi.translator.translate_calc_fields_in_transformed", return_value=transformed):
        transformed = translate_calc_fields_in_transformed(transformed)
    generate(transformed, tmp_path, Path("data"))
    tmdl_files = list(tmp_path.rglob("*.tmdl"))
    combined = "\n".join(f.read_text(encoding="utf-8") for f in tmdl_files)
    assert "DatabricksMultiCloud.Catalogs" in combined
    assert 'error "Unsupported connection type' not in combined
