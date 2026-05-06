"""T12: Physical joins, custom SQL, live connections, data blending detection."""

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

from tab_to_pbi.parser import (
    parse,
    _parse_physical_joins,
    _detect_unsupported,
    _parse_datasources,
)
from tab_to_pbi.transformer import transform, _apply_storage_mode
from tab_to_pbi.generator import generate
from tab_to_pbi.translator import _blocklist_check
from tab_to_pbi.validator import validate

SIMPLE = Path("input/simple.twb")
SIMPLE_JOIN = Path("input/simple_join.twb")
SIMPLE_JOIN_CALC = Path("input/simple_join_calculated_line.twb")
SUPERSTORE = Path("input/Superstore.twb")
TABPBI = Path("input/tabpbi.twbx")


# ---------------------------------------------------------------------------
# _parse_physical_joins unit tests
# ---------------------------------------------------------------------------

def _make_conn(join_type: str, left: str, right: str, left_col: str, right_col: str) -> ET.Element:
    """Build a minimal federated connection element with a physical join."""
    xml = f"""<connection class="federated">
      <relation join="{join_type}" type="join">
        <clause type="join">
          <expression op="=">
            <expression op="[{left}].[{left_col}]"/>
            <expression op="[{right}].[{right_col}]"/>
          </expression>
        </clause>
        <relation name="{left}" table="[schema].[{left}]" type="table"/>
        <relation name="{right}" table="[schema].[{right}]" type="table"/>
      </relation>
    </connection>"""
    return ET.fromstring(xml)


def test_physical_join_inner():
    conn = _make_conn("inner", "Orders", "Returns", "order_id", "order_id")
    rels, flags = _parse_physical_joins(conn)
    assert len(rels) == 1
    assert rels[0]["from_table"] == "Orders"
    assert rels[0]["to_table"] == "Returns"
    assert rels[0]["from_column"] == "order_id"
    assert flags == []


def test_physical_join_left():
    conn = _make_conn("left", "Orders", "Returns", "id", "order_id")
    rels, flags = _parse_physical_joins(conn)
    assert len(rels) == 1
    assert rels[0]["from_table"] == "Orders"
    assert flags == []


def test_physical_join_right_flipped_to_left():
    conn = _make_conn("right", "Orders", "Returns", "id", "order_id")
    rels, flags = _parse_physical_joins(conn)
    assert len(rels) == 1
    # RIGHT is flipped: Returns becomes from_table
    assert rels[0]["from_table"] == "Returns"
    assert rels[0]["to_table"] == "Orders"
    assert flags == []


def test_physical_join_full_outer_flagged():
    xml = """<connection class="federated">
      <relation join="fullouter" type="join">
        <relation name="Orders" type="table"/>
        <relation name="Returns" type="table"/>
      </relation>
    </connection>"""
    conn = ET.fromstring(xml)
    rels, flags = _parse_physical_joins(conn)
    assert rels == []
    assert any("FULL OUTER" in f for f in flags)


def test_physical_join_full_schema_value_flagged():
    """Schema JoinType-ST uses 'full' (not 'fullouter') — must still be flagged."""
    xml = """<connection class="federated">
      <relation join="full" type="join">
        <relation name="Orders" type="table"/>
        <relation name="Returns" type="table"/>
      </relation>
    </connection>"""
    conn = ET.fromstring(xml)
    rels, flags = _parse_physical_joins(conn)
    assert rels == []
    assert any("FULL OUTER" in f for f in flags)


def test_physical_join_none_when_collection():
    xml = """<connection class="federated">
      <relation type="collection">
        <relation name="Orders" type="table"/>
      </relation>
    </connection>"""
    conn = ET.fromstring(xml)
    rels, flags = _parse_physical_joins(conn)
    assert rels == [] and flags == []


# ---------------------------------------------------------------------------
# Live connection detection
# ---------------------------------------------------------------------------

def _make_ds_xml(conn_class: str, has_extract: bool = False) -> ET.Element:
    extract = "<extract count='-1' enabled='true' units='records'/>" if has_extract else ""
    return ET.fromstring(f"""<datasource name='test' caption='Test'>
      <connection class='{conn_class}' server='host' dbname='db'>
        <relation name='orders' table='[schema].[orders]' type='table'/>
      </connection>
      {extract}
    </datasource>""")


def test_live_connection_detected_for_postgres_without_extract():
    from tab_to_pbi.parser import _parse_connection
    ds = _make_ds_xml("postgres", has_extract=False)
    conn = _parse_connection(ds)
    assert conn["live_connection"] is True


def test_no_live_connection_for_postgres_with_extract():
    from tab_to_pbi.parser import _parse_connection
    ds = _make_ds_xml("postgres", has_extract=True)
    conn = _parse_connection(ds)
    assert conn["live_connection"] is False


def test_no_live_connection_for_excel():
    from tab_to_pbi.parser import _parse_connection
    ds = _make_ds_xml("excel-direct", has_extract=False)
    conn = _parse_connection(ds)
    assert conn["live_connection"] is False


# ---------------------------------------------------------------------------
# storage_mode propagation
# ---------------------------------------------------------------------------

def test_apply_storage_mode_import():
    conn = {"type": "excel-direct", "live_connection": False}
    result = _apply_storage_mode(conn)
    assert result["storage_mode"] == "import"


def test_apply_storage_mode_directquery():
    conn = {"type": "postgres", "live_connection": True}
    result = _apply_storage_mode(conn)
    assert result["storage_mode"] == "directQuery"


# ---------------------------------------------------------------------------
# Data blending detection
# ---------------------------------------------------------------------------

def test_data_blending_detected_in_superstore():
    workbook = parse(SUPERSTORE)
    blending = [u for u in workbook["unsupported"] if "data blending" in u]
    assert len(blending) >= 1
    assert "Performance" in blending[0]


def test_no_data_blending_in_simple():
    workbook = parse(SIMPLE)
    blending = [u for u in workbook["unsupported"] if "data blending" in u]
    assert blending == []


def test_no_data_blending_in_simple_join():
    workbook = parse(SIMPLE_JOIN)
    blending = [u for u in workbook["unsupported"] if "data blending" in u]
    assert blending == []


# ---------------------------------------------------------------------------
# Custom SQL detection
# ---------------------------------------------------------------------------

def test_custom_sql_message_in_unsupported():
    xml = """<workbook>
      <datasources>
        <datasource name="test_ds" caption="Test">
          <connection class="postgres" server="host" dbname="db">
            <relation name="Custom SQL" type="text">SELECT * FROM orders</relation>
          </connection>
        </datasource>
      </datasources>
      <worksheets/>
    </workbook>"""
    root = ET.fromstring(xml)
    datasources, _ = _parse_datasources(root)
    issues = _detect_unsupported(root, datasources)
    custom_sql_issues = [i for i in issues if "Custom SQL" in i]
    assert len(custom_sql_issues) == 1


# ---------------------------------------------------------------------------
# DirectQuery DAX blocklist
# ---------------------------------------------------------------------------

def test_blocklist_catches_median():
    assert _blocklist_check("MEDIAN('Table'[Score])") is True


def test_blocklist_catches_percentile():
    assert _blocklist_check("PERCENTILE.INC('Table'[Score], 0.9)") is True


def test_blocklist_allows_sum():
    assert _blocklist_check("SUM('Table'[Sales])") is False


def test_blocklist_allows_calculate():
    assert _blocklist_check("CALCULATE(SUM('Orders'[Sales]), ALL('Orders'))") is False


# ---------------------------------------------------------------------------
# End-to-end: all input files parse + transform + generate + validate
# ---------------------------------------------------------------------------

def _mock_translate(formula, table_name, columns=None, directquery=False, all_tables=None):
    if any(m in formula for m in ("[Parameters].", "[federated.", "INDEX()")):
        return ("", "unsupported")
    return (f"MOCK_DAX({table_name})", "translated")


@pytest.mark.parametrize("twb_path", [
    SIMPLE,
    SIMPLE_JOIN,
    SIMPLE_JOIN_CALC,
    SUPERSTORE,
    TABPBI,
])
def test_e2e_all_inputs_no_pipeline_errors(tmp_path, twb_path):
    with patch("tab_to_pbi.translator.translate_formula", side_effect=_mock_translate):
        from tab_to_pbi import main as main_mod
        import importlib
        # Use the pipeline directly
        from tab_to_pbi.transformer import transform
        from tab_to_pbi.translator import translate_calc_fields_in_transformed
        from tab_to_pbi.generator import generate
        from tab_to_pbi.validator import validate

        if twb_path.suffix == ".twbx":
            from tab_to_pbi.parser import extract_twbx_data
            data_dir = tmp_path / "data"
            extract_twbx_data(twb_path, data_dir)
        else:
            data_dir = Path("data")

        workbook = parse(twb_path)
        transformed = transform(workbook)
        transformed = translate_calc_fields_in_transformed(transformed)
        report_dir = generate(transformed, tmp_path, data_dir)
        result = validate(report_dir)
        errors = [r for r in result if r.level == "error"]
        assert errors == [], f"{twb_path.name}: {[r.message for r in errors]}"


def test_superstore_blending_sheet_in_unsupported(tmp_path):
    """Data blending flag must appear in migration_report unsupported list."""
    workbook = parse(SUPERSTORE)
    transformed = transform(workbook)
    unsupported = transformed["report"]["unsupported"]
    blending = [u for u in unsupported if "data blending" in u]
    assert len(blending) >= 1


def test_live_connection_flag_generates_directquery_tmdl(tmp_path):
    """A datasource with live_connection=True must write mode: directQuery in TMDL."""
    xml = """<workbook>
      <datasources>
        <datasource name="live_ds" caption="LiveDS">
          <connection class="postgres" server="host" dbname="mydb">
            <relation name="orders" table="[public].[orders]" type="table"/>
          </connection>
        </datasource>
      </datasources>
      <worksheets/>
    </workbook>"""
    root = ET.fromstring(xml)
    datasources, _ = _parse_datasources(root)
    assert datasources[0]["connection"]["live_connection"] is True

    from tab_to_pbi.transformer import transform as tf
    workbook = {"name": "live_test", "datasources": datasources, "sheets": [], "unsupported": []}
    transformed = tf(workbook)
    report_dir = generate(transformed, tmp_path)
    model_tmdl = (tmp_path / "live_test.SemanticModel" / "definition" / "model.tmdl").read_text()
    assert "directQuery" in model_tmdl


# ---------------------------------------------------------------------------
# Schema conformance fixes (2026-04-20)
# ---------------------------------------------------------------------------

def test_unsupported_relation_type_union_flagged():
    """Relation type 'union' must be reported as unsupported."""
    xml = """<workbook>
      <datasources>
        <datasource name="ds1" caption="DS1">
          <connection class="postgres" server="h" dbname="d">
            <relation type="union" name="my_union"/>
          </connection>
        </datasource>
      </datasources>
      <worksheets/>
    </workbook>"""
    root = ET.fromstring(xml)
    datasources, _ = _parse_datasources(root)
    issues = _detect_unsupported(root, datasources)
    union_issues = [i for i in issues if "union" in i]
    assert len(union_issues) == 1


def test_unsupported_relation_type_subquery_flagged():
    """Relation type 'subquery' must be reported as unsupported."""
    xml = """<workbook>
      <datasources>
        <datasource name="ds1" caption="DS1">
          <connection class="postgres" server="h" dbname="d">
            <relation type="subquery" name="sub"/>
          </connection>
        </datasource>
      </datasources>
      <worksheets/>
    </workbook>"""
    root = ET.fromstring(xml)
    datasources, _ = _parse_datasources(root)
    issues = _detect_unsupported(root, datasources)
    assert any("subquery" in i for i in issues)


def test_extract_disabled_treated_as_live():
    """extract element with enabled='false' must be treated as live connection."""
    from tab_to_pbi.parser import _parse_connection
    ds = ET.fromstring("""<datasource name='test' caption='Test'>
      <connection class='postgres' server='host' dbname='db'>
        <relation name='orders' table='[public].[orders]' type='table'/>
      </connection>
      <extract count='-1' enabled='false' units='records'/>
    </datasource>""")
    conn = _parse_connection(ds)
    assert conn["live_connection"] is True


def test_parent_name_fallback_for_source_table():
    """parent-name in metadata-records must be used when cols/map is absent."""
    from tab_to_pbi.parser import _parse_columns
    ds = ET.fromstring("""<datasource name='test'>
      <connection class='postgres'>
        <relation type='collection'>
          <relation name='orders' table='[schema].[orders]' type='table'/>
        </relation>
        <metadata-records>
          <metadata-record class='column'>
            <local-name>[order_id]</local-name>
            <parent-name>[orders]</parent-name>
            <local-type>integer</local-type>
          </metadata-record>
        </metadata-records>
      </connection>
    </datasource>""")
    conn_dict = {"type": "postgres"}
    cols = _parse_columns(ds, conn_dict)
    assert len(cols) == 1
    assert cols[0]["source_table"] == "orders"


def test_mark_orientation_parsed():
    """mark_orientation must be extracted from the mark element."""
    from tab_to_pbi.parser import _parse_sheets
    root = ET.fromstring("""<workbook>
      <worksheets>
        <worksheet name='Sheet1'>
          <table>
            <view>
              <datasource-dependencies datasource='ds1'/>
            </view>
            <rows></rows>
            <cols></cols>
            <panes>
              <pane>
                <mark class='Bar' orientation='y'/>
              </pane>
            </panes>
          </table>
        </worksheet>
      </worksheets>
    </workbook>""")
    sheets = _parse_sheets(root)
    assert sheets[0]["mark_orientation"] == "y"
