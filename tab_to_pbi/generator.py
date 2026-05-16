"""Write PBIR folder structure from transformed workbook dict."""

import hashlib
import json
from pathlib import Path

MARK_TO_VISUAL = {
    "Automatic": "tableEx",
    "Bar": "barChart",
    "Column": "columnChart",
    "Line": "lineChart",
    "Area": "areaChart",
    "Pie": "pieChart",
    "Circle": "scatterChart",
    "Shape": "scatterChart",
    "Polygon": "filledMap",
    "Multipolygon": "filledMap",
    "PolyLine": "map",
    "Text": "tableEx",
    "CrossTab": "pivotTable",
    "KPI": "cardVisual",
}

_SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report"

# Maps Tableau aggregation prefix → PBI semantic query Aggregation.Function integer
_PBI_AGG_FUNC = {
    "sum": 0,
    "avg": 1,
    "average": 1,
    "cntd": 2,
    "ctd": 2,
    "min": 3,
    "max": 4,
    "cnt": 5,
    "median": 6,
}

# Maps PBI/TMDL dataType → Power Query M type literal
_M_TYPE_MAP = {
    "string":   "type text",
    "int64":    "Int64.Type",
    "double":   "Decimal.Type",
    "dateTime": "type datetime",
    "boolean":  "type logical",
}

# SQL date-part extraction per dialect (DirectQuery mode).
# All expressions are sourced from official vendor documentation.
_DATE_PART_SQL: dict[str, dict[str, str]] = {
    "postgres": {
        "YEAR":    "EXTRACT(YEAR FROM {col})",
        "QUARTER": "EXTRACT(QUARTER FROM {col})",
        "MONTH":   "EXTRACT(MONTH FROM {col})",
        "WEEKNUM": "EXTRACT(WEEK FROM {col})",
        "DAY":     "EXTRACT(DAY FROM {col})",
        "HOUR":    "EXTRACT(HOUR FROM {col})",
        "MINUTE":  "EXTRACT(MINUTE FROM {col})",
        "SECOND":  "EXTRACT(SECOND FROM {col})",
    },
    "redshift": {   # AWS Redshift: PostgreSQL-dialect EXTRACT
        "YEAR":    "EXTRACT(YEAR FROM {col})",
        "QUARTER": "EXTRACT(QUARTER FROM {col})",
        "MONTH":   "EXTRACT(MONTH FROM {col})",
        "WEEKNUM": "EXTRACT(WEEK FROM {col})",
        "DAY":     "EXTRACT(DAY FROM {col})",
        "HOUR":    "EXTRACT(HOUR FROM {col})",
        "MINUTE":  "EXTRACT(MINUTE FROM {col})",
        "SECOND":  "EXTRACT(SECOND FROM {col})",
    },
    "mysql": {
        "YEAR":    "YEAR({col})",
        "QUARTER": "QUARTER({col})",
        "MONTH":   "MONTH({col})",
        "WEEKNUM": "WEEK({col})",
        "DAY":     "DAY({col})",
        "HOUR":    "HOUR({col})",
        "MINUTE":  "MINUTE({col})",
        "SECOND":  "SECOND({col})",
    },
    "sqlserver": {
        "YEAR":    "YEAR({col})",
        "QUARTER": "DATEPART(quarter, {col})",
        "MONTH":   "MONTH({col})",
        "WEEKNUM": "DATEPART(week, {col})",
        "DAY":     "DAY({col})",
        "HOUR":    "DATEPART(hour, {col})",
        "MINUTE":  "DATEPART(minute, {col})",
        "SECOND":  "DATEPART(second, {col})",
    },
    "snowflake": {
        "YEAR":    "YEAR({col})",
        "QUARTER": "QUARTER({col})",
        "MONTH":   "MONTH({col})",
        "WEEKNUM": "WEEKOFYEAR({col})",
        "DAY":     "DAY({col})",
        "HOUR":    "HOUR({col})",
        "MINUTE":  "MINUTE({col})",
        "SECOND":  "SECOND({col})",
    },
    "bigquery": {
        "YEAR":    "EXTRACT(YEAR FROM {col})",
        "QUARTER": "EXTRACT(QUARTER FROM {col})",
        "MONTH":   "EXTRACT(MONTH FROM {col})",
        "WEEKNUM": "EXTRACT(WEEK FROM {col})",
        "DAY":     "EXTRACT(DAY FROM {col})",
        "HOUR":    "EXTRACT(HOUR FROM {col})",
        "MINUTE":  "EXTRACT(MINUTE FROM {col})",
        "SECOND":  "EXTRACT(SECOND FROM {col})",
    },
    "oracle": {
        "YEAR":    "EXTRACT(YEAR FROM {col})",
        "QUARTER": "TO_NUMBER(TO_CHAR({col}, 'Q'))",
        "MONTH":   "EXTRACT(MONTH FROM {col})",
        "WEEKNUM": "TO_NUMBER(TO_CHAR({col}, 'IW'))",  # ISO week
        "DAY":     "EXTRACT(DAY FROM {col})",
        "HOUR":    "TO_NUMBER(TO_CHAR({col}, 'HH24'))",
        "MINUTE":  "TO_NUMBER(TO_CHAR({col}, 'MI'))",
        "SECOND":  "TO_NUMBER(TO_CHAR({col}, 'SS'))",
    },
    "teradata": {
        "YEAR":    "EXTRACT(YEAR FROM {col})",
        "QUARTER": "CAST((EXTRACT(MONTH FROM {col}) + 2) / 3 AS INTEGER)",
        "MONTH":   "EXTRACT(MONTH FROM {col})",
        # TD_WEEK_OF_YEAR requires TD_SYSFNLIB to be installed on the Teradata instance
        "WEEKNUM": "TD_WEEK_OF_YEAR({col})",
        "DAY":     "EXTRACT(DAY FROM {col})",
        "HOUR":    "EXTRACT(HOUR FROM {col})",
        "MINUTE":  "EXTRACT(MINUTE FROM {col})",
        "SECOND":  "EXTRACT(SECOND FROM {col})",
    },
}

# Power Query M functions for date-part extraction (Import mode).
# Format: {part: (m_function_template, m_type_literal)}
# {col} placeholder is replaced with the actual column name at generation time.
_DATE_PART_M: dict[str, tuple[str, str]] = {
    "YEAR":    ('Date.Year([#"{col}"])',          "Int64.Type"),
    "QUARTER": ('Date.QuarterOfYear([#"{col}"])', "Int64.Type"),
    "MONTH":   ('Date.Month([#"{col}"])',         "Int64.Type"),
    "WEEKNUM": ('Date.WeekOfYear([#"{col}"])',    "Int64.Type"),
    "DAY":     ('Date.Day([#"{col}"])',           "Int64.Type"),
    "HOUR":    ('Time.Hour([#"{col}"])',          "Int64.Type"),
    "MINUTE":  ('Time.Minute([#"{col}"])',        "Int64.Type"),
    "SECOND":  ('Time.Second([#"{col}"])',        "Int64.Type"),
}

# Canonical coarse-to-fine ordering for hierarchy level emission
_PART_ORDER = ["YEAR", "QUARTER", "MONTH", "WEEKNUM", "DAY", "HOUR", "MINUTE", "SECOND"]
_PART_LABEL = {
    "YEAR": "Year", "QUARTER": "Quarter", "MONTH": "Month", "WEEKNUM": "Week",
    "DAY": "Day", "HOUR": "Hour", "MINUTE": "Minute", "SECOND": "Second",
}

# Standard drill-down levels emitted for DirectQuery custom SQL date columns.
# Matches the 4 levels PBI Auto date/time creates for Import mode (disabled for DQ).
_HIERARCHY_PARTS = ["YEAR", "QUARTER", "MONTH", "DAY"]


def _expand_to_hierarchy(dpc: list[dict]) -> list[dict]:
    """Expand date-part columns to full YEAR/QUARTER/MONTH/DAY per unique base column.

    For DirectQuery custom SQL, Auto date/time is disabled so we must emit all
    four standard levels explicitly to enable drill-down in PBI visuals.
    """
    base_cols: list[str] = []
    for dp in dpc:
        if dp["base_col"] not in base_cols:
            base_cols.append(dp["base_col"])
    return [
        {"base_col": bc, "part": part, "derived": f"{bc} {_PART_LABEL[part]}"}
        for bc in base_cols
        for part in _HIERARCHY_PARTS
    ]


def generate(transformed: dict, output_dir: Path, data_dir: Path = Path("data")) -> Path:
    """Write PBIR SemanticModel and Report files. Returns the Report folder path."""
    name = transformed["name"]
    report_dir = output_dir / f"{name}.Report"
    model_dir = output_dir / f"{name}.SemanticModel"
    definition_dir = report_dir / "definition"

    report_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    definition_dir.mkdir(parents=True, exist_ok=True)

    _write_definition_pbism(model_dir)
    _write_tmdl_model(model_dir, transformed, data_dir)
    _write_definition_pbir(report_dir, name)
    _write_version_json(definition_dir)
    _write_report_json(definition_dir, transformed.get("datasource_filters", []))
    _write_pages(definition_dir, transformed)

    return report_dir


def _format_literal(value: str) -> str:
    """Format a Tableau filter value string as a PBI semantic query literal."""
    v = value.strip()
    # Tableau date-only: #2023-01-03#  → date'2023-01-03'
    # Tableau datetime:  #2023-01-03 12:00:00#  → datetime'2023-01-03T12:00:00'
    if v.startswith("#") and v.endswith("#"):
        inner = v.strip("#").strip()
        if " " in inner:
            return f"datetime'{inner.replace(' ', 'T')}'"
        return f"date'{inner}'"
    try:
        float_val = float(v)
        int_val = int(float_val)
        return f"{v}L" if int_val == float_val and "." not in v else f"{v}D"
    except ValueError:
        return f"'{v}'"


def _build_filter_entry(f: dict, idx: int) -> dict | None:
    """Build one PBI filterConfig entry from an enriched filter dict."""
    field_name = f["field"]
    table_name = f.get("table", "")
    cls = f["class"]
    if not table_name:
        return None

    filter_id = hashlib.md5(f"{field_name}_{cls}_{idx}".encode()).hexdigest()[:20]
    field_ref = {
        "Column": {
            "Expression": {"SourceRef": {"Entity": table_name}},
            "Property": field_name,
        }
    }
    col_expr = {
        "Column": {
            "Expression": {"SourceRef": {"Source": "f"}},
            "Property": field_name,
        }
    }
    from_clause = [{"Name": "f", "Entity": table_name, "Type": 0}]

    if cls == "categorical":
        values = f.get("values", [])
        if not values:
            return None  # level-members only — no restriction to migrate
        condition = {
            "In": {
                "Expressions": [col_expr],
                "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values],
            }
        }
        filter_type = "Categorical"
        where = [{"Condition": condition}]
    elif cls == "quantitative":
        agg_prefix = f.get("agg_prefix")
        min_val = f.get("min", "")
        max_val = f.get("max", "")
        if agg_prefix and agg_prefix in _PBI_AGG_FUNC:
            # Post-aggregation filter: use Aggregation expression + Advanced type
            agg_func = _PBI_AGG_FUNC[agg_prefix]
            agg_expr = {
                "Aggregation": {
                    "Expression": col_expr,
                    "Function": agg_func,
                }
            }
            agg_field_ref = {
                "Aggregation": {
                    "Expression": {
                        "Column": {
                            "Expression": {"SourceRef": {"Entity": table_name}},
                            "Property": field_name,
                        }
                    },
                    "Function": agg_func,
                }
            }
            where = []
            if min_val:
                where.append({"Condition": {"Comparison": {"ComparisonKind": 2, "Left": agg_expr, "Right": {"Literal": {"Value": _format_literal(min_val)}}}}})
            if max_val:
                where.append({"Condition": {"Comparison": {"ComparisonKind": 4, "Left": agg_expr, "Right": {"Literal": {"Value": _format_literal(max_val)}}}}})
            if not where:
                return None
            filter_type = "Advanced"
            field_ref = agg_field_ref
        else:
            # Row-level filter: use raw Column expression + Range type
            if min_val and max_val:
                where = [{"Condition": {"Between": {"Expression": col_expr, "LowerBound": {"Literal": {"Value": _format_literal(min_val)}}, "UpperBound": {"Literal": {"Value": _format_literal(max_val)}}}}}]
            elif min_val:
                where = [{"Condition": {"Comparison": {"ComparisonKind": 2, "Left": col_expr, "Right": {"Literal": {"Value": _format_literal(min_val)}}}}}]
            elif max_val:
                where = [{"Condition": {"Comparison": {"ComparisonKind": 4, "Left": col_expr, "Right": {"Literal": {"Value": _format_literal(max_val)}}}}}]
            else:
                return None
            filter_type = "Range"
    else:
        return None

    return {
        "name": filter_id,
        "field": field_ref,
        "type": filter_type,
        "filter": {
            "Version": 2,
            "From": from_clause,
            "Where": where,
        },
        "howCreated": "User",
        "isHiddenInViewMode": False,
    }


def _build_filter_config(filters: list[dict]) -> dict | None:
    """Build a PBI filterConfig dict from a list of enriched filter dicts."""
    entries = [e for i, f in enumerate(filters) for e in [_build_filter_entry(f, i)] if e]
    return {"filters": entries} if entries else None


def _write_definition_pbism(model_dir: Path) -> None:
    """Write definition.pbism."""
    (model_dir / "definition.pbism").write_text(
        json.dumps({"version": "4.0", "settings": {}}, indent=2)
    )


def _tmdl_id(name: str) -> str:
    """Quote a TMDL identifier that contains spaces or special characters."""
    if any(c in name for c in " ()/-.,"):
        return f"'{name}'"
    return name


def _m_sql_alias(conn_type: str, name: str) -> str:
    """SQL column alias pre-escaped for embedding inside an M text literal (double-quote delimited)."""
    if conn_type == "mysql":
        return f"`{name.replace('`', '``')}`"
    if conn_type == "sqlserver":
        return f"[{name.replace(']', ']]')}]"
    # ANSI double-quote identifiers; each " becomes "" inside an M string literal
    esc = name.replace('"', '""')
    return f'""{ esc }""'


def _m_sql_table(conn_type: str, schema: str, table_name: str) -> str:
    """Qualified table reference for embedding inside an M NativeQuery SQL string."""
    if conn_type == "mysql":
        s = f"`{schema}`." if schema else ""
        return f"{s}`{table_name}`"
    if conn_type == "sqlserver":
        s = f"[{schema.replace(']', ']]')}]." if schema else ""
        return f"{s}[{table_name.replace(']', ']]')}]"
    # ANSI: each " becomes "" for M string embedding
    esc_s = schema.replace('"', '""')
    esc_t = table_name.replace('"', '""')
    s = f'""{ esc_s }"".' if schema else ""
    return f'{s}""{ esc_t }""'


def _write_tmdl_model(model_dir: Path, transformed: dict, data_dir: Path) -> None:
    """Write TMDL semantic model: definition/model.tmdl + definition/tables/<name>.tmdl."""
    defn_dir = model_dir / "definition"
    tables_dir = defn_dir / "tables"
    defn_dir.mkdir(exist_ok=True)
    tables_dir.mkdir(exist_ok=True)

    # Remove legacy TMSL file if present
    legacy_bim = model_dir / "model.bim"
    if legacy_bim.exists():
        legacy_bim.unlink()

    # Remove stale table files from prior runs before writing new ones
    for stale in tables_dir.glob("*.tmdl"):
        stale.unlink()

    name = transformed["name"]
    database_tmdl = f"database '{name}'\n\tcompatibilityLevel: 1600\n"
    (defn_dir / "database.tmdl").write_text(database_tmdl, encoding="utf-8")

    has_dq = any(
        t.get("connection", {}).get("storage_mode") == "directQuery"
        for t in transformed.get("tables", [])
    )
    model_tmdl = (
        "model Model\n"
        "\tculture: en-US\n"
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
    )
    if has_dq:
        model_tmdl += "\tdefaultMode: directQuery\n"
    (defn_dir / "model.tmdl").write_text(model_tmdl, encoding="utf-8")

    # Write relationships as a standalone file (PBI Desktop format)
    rels = transformed.get("relationships", [])
    rel_path = defn_dir / "relationships.tmdl"
    if rels:
        rel_lines = []
        for r in rels:
            from_card = r.get("from_cardinality", "many")
            to_card = r.get("to_cardinality", "one")
            # PBI TMDL requires fromColumn = MANY side; swap if our inference put ONE side as from
            if from_card == "one" and to_card == "many":
                from_tbl, from_col = r["to_table"], r["to_column"]
                to_tbl, to_col = r["from_table"], r["from_column"]
                from_card, to_card = "many", "one"
            else:
                from_tbl, from_col = r["from_table"], r["from_column"]
                to_tbl, to_col = r["to_table"], r["to_column"]
            rel_name = f"{from_tbl}_{from_col} -> {to_tbl}_{to_col}"
            lines = [
                f"relationship '{rel_name}'",
                f"\tfromColumn: {_tmdl_id(from_tbl)}.{_tmdl_id(from_col)}",
                f"\ttoColumn: {_tmdl_id(to_tbl)}.{_tmdl_id(to_col)}",
            ]
            if (from_card, to_card) != ("many", "one"):
                lines.append(f"\tfromCardinality: {from_card}")
                lines.append(f"\ttoCardinality: {to_card}")
            if (from_card, to_card) in (("one", "one"), ("many", "many")):
                lines.append("\tcrossFilteringBehavior: bothDirections")
            lines.append("")
            rel_lines += lines
        rel_path.write_text("\n".join(rel_lines), encoding="utf-8")
    elif rel_path.exists():
        rel_path.unlink()

    measures_by_table: dict[str, list] = {}
    for m in transformed.get("measures", []):
        measures_by_table.setdefault(m["table"], []).append(m)

    for table in transformed.get("tables", []):
        _write_tmdl_table(tables_dir, table, data_dir, measures_by_table.get(table["name"], []))


def _tmdl_measure_lines(name_q: str, dax: str) -> list[str]:
    """Return TMDL lines for a measure declaration.

    Single-line DAX: written inline after '='.
    Multiline DAX: expression starts on the next line at Level 3 (3 tabs),
    per TMDL spec — each 2-space Claude indent level maps to one extra tab.
    """
    if "\n" not in dax:
        return [f"\tmeasure {name_q} = {dax}"]
    result = [f"\tmeasure {name_q} ="]
    for line in dax.splitlines():
        if not line.strip():
            result.append("")
        else:
            leading = len(line) - len(line.lstrip(" "))
            result.append("\t" * (3 + leading // 2) + line.lstrip(" "))
    return result


def _write_tmdl_table(tables_dir: Path, table: dict, data_dir: Path, measures: list | None = None) -> None:
    """Write one TMDL table file."""
    name = table["name"]
    qname = _tmdl_id(name)
    lines = [f"table {qname}", ""]

    for col in table["columns"]:
        lines.append(f"\tcolumn {_tmdl_id(col['name'])}")
        lines.append(f"\t\tdataType: {col['dataType']}")
        lines.append(f"\t\tsourceColumn: {col['name']}")
        lines.append("")

    for m in measures:
        lines.extend(_tmdl_measure_lines(_tmdl_id(m['name']), m['dax']))
        lines.append("")

    conn = table["connection"]
    storage_mode = conn.get("storage_mode", "import")

    # Derived date-part columns (added via M expression; regular columns in TMDL)
    dpc = table.get("date_part_columns", [])
    # For custom SQL DirectQuery, PBI's Auto date/time is disabled — expand to full
    # YEAR/QUARTER/MONTH/DAY hierarchy so drill-down works like Import mode.
    if conn.get("custom_sql") and storage_mode == "directQuery" and dpc:
        dpc = _expand_to_hierarchy(dpc)
    for dp in dpc:
        lines.append(f"\tcolumn {_tmdl_id(dp['derived'])}")
        lines.append(f"\t\tdataType: int64")
        lines.append(f"\t\tsourceColumn: {dp['derived']}")
        lines.append("")

    # Hierarchy block: emitted when 2+ date-part levels exist for the same base column
    by_base: dict[str, list] = {}
    for dp in dpc:
        by_base.setdefault(dp["base_col"], []).append(dp)
    col_names_lower = {c["name"].lower() for c in table["columns"]}
    for base_col, parts in by_base.items():
        if len(parts) < 2:
            continue
        hier_name = " ".join(w.capitalize() for w in base_col.replace("_", " ").split())
        # PBI names are case-insensitive within a table — avoid collision with the base column
        if hier_name.lower() in col_names_lower:
            hier_name = f"{base_col} Hierarchy"
        sorted_parts = sorted(parts, key=lambda p: _PART_ORDER.index(p["part"]) if p["part"] in _PART_ORDER else 99)
        lines.append(f"\thierarchy {_tmdl_id(hier_name)}")
        for p in sorted_parts:
            level_label = _PART_LABEL.get(p["part"], p["part"].capitalize())
            lines.append(f"\t\tlevel {_tmdl_id(level_label)}")
            lines.append(f"\t\t\tcolumn: {_tmdl_id(p['derived'])}")
        lines.append("")

    if measures is None:
        measures = []
    expr_lines, use_backtick = _build_m_expression(conn, data_dir, table["columns"], dpc)
    lines.append(f"\tpartition {qname} = m")
    lines.append(f"\t\tmode: {storage_mode}")
    if use_backtick:
        lines.append("\t\tsource = ```")
        for line in expr_lines:
            lines.append(f"\t\t\t{line}")
        lines.append("\t\t\t```")
    else:
        lines.append("\t\tsource =")
        for line in expr_lines:
            lines.append(f"\t\t\t{line}")
    lines.append("")

    safe_name = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    (tables_dir / f"{safe_name}.tmdl").write_text("\n".join(lines), encoding="utf-8")


def _chain_add_columns(lines: list[str], prev: str, dpc: list[dict]) -> tuple[list[str], str]:
    """Append Table.AddColumn steps for date-part columns (Import mode).

    Expects lines to end with ["in", "    {prev}"]. Removes those, adds a trailing
    comma to the last let-binding, chains AddColumn steps, then re-appends "in / last".
    Returns (new_lines, new_last_step_name).
    """
    if not dpc:
        return lines, prev
    result = list(lines[:-2])
    result[-1] += ","
    curr = prev
    for i, dp in enumerate(dpc):
        if dp["part"] not in _DATE_PART_M:
            continue
        m_fn, m_type = _DATE_PART_M[dp["part"]]
        m_expr = m_fn.format(col=dp["base_col"])
        var = f"add_dp_{i}"
        result.append(f'    {var} = Table.AddColumn({curr}, "{dp["derived"]}", each {m_expr}, {m_type}),')
        curr = var
    # Remove trailing comma from the last step
    result[-1] = result[-1].rstrip(",")
    result.extend(["in", f"    {curr}"])
    return result, curr


def _build_m_expression(
    conn: dict,
    data_dir: Path,
    columns: list[dict] | None = None,
    date_part_columns: list[dict] | None = None,
) -> tuple[list[str], bool]:
    """Build Power Query M expression lines from connection info.

    Returns (lines, use_backtick). use_backtick is True when the expression contains
    a multi-line SQL string that requires TMDL triple-backtick wrapping to avoid
    indentation parse errors (per TMDL spec — backticks disable indentation rules).

    For file-based sources (Excel, CSV), appends an explicit Table.TransformColumnTypes
    step derived from Tableau column metadata so PBI doesn't mistype numeric columns.
    date_part_columns: list of {base_col, part, derived} dicts for date-part extraction.
    """
    conn_type = conn.get("type", "")

    def _type_step(prev: str) -> list[str]:
        """Return lines for Table.TransformColumnTypes, or empty list if no columns."""
        if not columns:
            return []
        pairs = [
            f'        {{"{col["name"].replace(chr(34), chr(34)*2)}", {_M_TYPE_MAP[col["dataType"]]}}}'
            for col in columns
            if col["dataType"] in _M_TYPE_MAP
        ]
        if not pairs:
            return []
        return [
            f'    #"Changed Types" = Table.TransformColumnTypes({prev}, {{',
            *[p + "," for p in pairs[:-1]],
            pairs[-1],
            "    })",
        ]

    stem = Path(conn.get("filename", "")).stem
    xlsx = data_dir / f"{stem}.xlsx"
    xls = data_dir / f"{stem}.xls"
    resolved = xlsx if xlsx.exists() else xls
    filename = resolved.resolve().as_posix()
    table_name = conn.get("table_name", "")
    safe_var = table_name.replace(" ", "_").replace("-", "_")
    escaped_table = table_name.replace('"', '""')

    dpc = date_part_columns or []

    if conn_type == "excel-direct":
        type_lines = _type_step('#"Promoted Headers"')
        last_step = '#"Changed Types"' if type_lines else '#"Promoted Headers"'
        base_lines = [
            "let",
            f'    Source = Excel.Workbook(File.Contents("{filename}"), null, true),',
            f'    {safe_var}_Sheet = Source{{[Item="{escaped_table}",Kind="Sheet"]}}[Data],',
            f'    #"Promoted Headers" = Table.PromoteHeaders({safe_var}_Sheet, [PromoteAllScalars=true])'
            + ("," if type_lines else ""),
            *type_lines,
            "in",
            f"    {last_step}",
        ]
        lines, _ = _chain_add_columns(base_lines, last_step, dpc)
        return lines, False

    if conn_type == "textscan":
        csv_path = (data_dir / conn.get("filename", "")).resolve().as_posix()
        type_lines = _type_step('#"Promoted Headers"')
        last_step = '#"Changed Types"' if type_lines else '#"Promoted Headers"'
        base_lines = [
            "let",
            f'    Source = Csv.Document(File.Contents("{csv_path}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.None]),',
            f'    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true])'
            + ("," if type_lines else ""),
            *type_lines,
            "in",
            f"    {last_step}",
        ]
        lines, _ = _chain_add_columns(base_lines, last_step, dpc)
        return lines, False

    # SQL-based connections share the same structure; only the M connector function differs.
    # Snowflake and Databricks use hierarchical navigation and have their own branches below.
    _SQL_CONNECTOR = {
        "postgres":  "PostgreSQL.Database",
        "sqlserver": "Sql.Database",
        "mysql":     "MySQL.Database",
        "redshift":  "AmazonRedshift.Database",
        "oracle":    "Oracle.Database",
        "bigquery":  "GoogleBigQuery.Database",
        "teradata":  "Teradata.Database",
    }

    if conn_type in _SQL_CONNECTOR:
        fn = _SQL_CONNECTOR[conn_type]
        server = conn.get("server", "")
        dbname = conn.get("dbname", "")
        custom_sql = conn.get("custom_sql", "")
        storage_mode = conn.get("storage_mode", "import")

        if custom_sql:
            # use_backtick=True: multi-line SQL requires TMDL triple-backtick wrapping.
            if dpc and storage_mode == "directQuery":
                # Wrap custom SQL as subquery so EXTRACT columns exist in the result.
                # PBI DirectQuery folding generates SELECT t0."col" FROM (<query>) t0 —
                # the derived column must be present in the subquery SELECT list.
                dialect = _DATE_PART_SQL.get(conn_type, {})
                select_parts = []
                for dp in dpc:
                    if dp["part"] not in dialect:
                        continue
                    sql_fn = dialect[dp["part"]].format(col=f't0.{dp["base_col"]}')
                    # Raw SQL alias (no M-escaping yet; whole string is escaped after)
                    if conn_type == "mysql":
                        alias = f"`{dp['derived'].replace('`', '``')}`"
                    elif conn_type == "sqlserver":
                        alias = f"[{dp['derived'].replace(']', ']]')}]"
                    else:
                        alias = f'"{dp["derived"]}"'
                    select_parts.append(f"{sql_fn} AS {alias}")
                if select_parts:
                    wrapped = f'SELECT t0.*, {", ".join(select_parts)} FROM ({custom_sql}) t0'
                    escaped = wrapped.replace('"', '""')
                    return [
                        "let",
                        f'    Source = {fn}("{server}", "{dbname}"),',
                        f'    nav = Value.NativeQuery(Source, "{escaped}", null, [EnableFolding=true])',
                        "in",
                        "    nav",
                    ], True

            if dpc and storage_mode != "directQuery":
                # Import mode: chain Table.AddColumn steps after NativeQuery
                escaped_sql = custom_sql.replace('"', '""')
                base_lines = [
                    "let",
                    f'    Source = {fn}("{server}", "{dbname}"),',
                    f'    nav = Value.NativeQuery(Source, "{escaped_sql}", null, [EnableFolding=true])',
                    "in",
                    "    nav",
                ]
                lines, _ = _chain_add_columns(base_lines, "nav", dpc)
                return lines, True

            escaped_sql = custom_sql.replace('"', '""')
            return [
                "let",
                f'    Source = {fn}("{server}", "{dbname}"),',
                f'    nav = Value.NativeQuery(Source, "{escaped_sql}", null, [EnableFolding=true])',
                "in",
                "    nav",
            ], True

        schema = conn.get("schema", "")
        table = conn.get("table", "")

        if dpc and storage_mode == "directQuery":
            # DirectQuery with date-part columns: use NativeQuery with per-dialect SQL
            # so the expressions are guaranteed to execute (no M-folding dependency).
            dialect = _DATE_PART_SQL.get(conn_type, {})
            select_parts = []
            for dp in dpc:
                sql_expr = dialect.get(dp["part"], "").format(col=dp["base_col"])
                if not sql_expr:
                    continue
                alias = _m_sql_alias(conn_type, dp["derived"])
                select_parts.append(f"{sql_expr} AS {alias}")
            if select_parts:
                qual = _m_sql_table(conn_type, schema, table)
                sql = f"SELECT *, {', '.join(select_parts)} FROM {qual}"
                return [
                    "let",
                    f'    Source = {fn}("{server}", "{dbname}"),',
                    f'    nav = Value.NativeQuery(Source, "{sql}", null, [EnableFolding=true])',
                    "in",
                    "    nav",
                ], False

        # Import mode (or DirectQuery with no date-part columns)
        base_lines = [
            "let",
            f'    Source = {fn}("{server}", "{dbname}"),',
            f'    nav = Source{{[Schema="{schema}", Item="{table}"]}}[Data]',
            "in",
            "    nav",
        ]
        if dpc and storage_mode != "directQuery":
            base_lines, _ = _chain_add_columns(base_lines, "nav", dpc)
        return base_lines, False

    if conn_type == "snowflake":
        server    = conn.get("server", "")
        warehouse = conn.get("warehouse", "")
        dbname    = conn.get("dbname", "")
        schema    = conn.get("schema", "")
        table     = conn.get("table", "")
        custom_sql = conn.get("custom_sql", "")
        storage_mode = conn.get("storage_mode", "import")
        # Warehouse is the 2nd positional arg; Implementation="2.0" selects the ADBC driver
        # (default for new connections since March 2025 per Microsoft docs).
        opts = f'"{warehouse}", [Implementation="2.0"]' if warehouse else '[Implementation="2.0"]'
        source_line = f'    Source = Snowflake.Databases("{server}", {opts}),'
        # Snowflake.Databases() returns a navigation table, not a connection.
        # Value.NativeQuery requires the database-level object — navigate first.
        db_var = f"{dbname}_Database"
        db_nav_line = f'    {db_var} = Source{{[Name="{dbname}",Kind="Database"]}}[Data],'

        if custom_sql:
            if dpc and storage_mode == "directQuery":
                dialect = _DATE_PART_SQL.get("snowflake", {})
                select_parts = []
                for dp in dpc:
                    if dp["part"] not in dialect:
                        continue
                    sql_fn = dialect[dp["part"]].format(col=f't0.{dp["base_col"]}')
                    alias = _m_sql_alias("snowflake", dp["derived"])
                    select_parts.append(f"{sql_fn} AS {alias}")
                if select_parts:
                    wrapped = f'SELECT t0.*, {", ".join(select_parts)} FROM ({custom_sql}) t0'
                    escaped = wrapped.replace('"', '""')
                    return [
                        "let",
                        source_line,
                        db_nav_line,
                        f'    nav = Value.NativeQuery({db_var}, "{escaped}", null, [EnableFolding=true])',
                        "in",
                        "    nav",
                    ], True
            escaped_sql = custom_sql.replace('"', '""')
            base_lines = [
                "let",
                source_line,
                db_nav_line,
                f'    nav = Value.NativeQuery({db_var}, "{escaped_sql}", null, [EnableFolding=true])',
                "in",
                "    nav",
            ]
            if dpc and storage_mode != "directQuery":
                base_lines, _ = _chain_add_columns(base_lines, "nav", dpc)
            return base_lines, True

        if dpc and storage_mode == "directQuery":
            dialect = _DATE_PART_SQL.get("snowflake", {})
            select_parts = []
            for dp in dpc:
                sql_expr = dialect.get(dp["part"], "").format(col=dp["base_col"])
                if not sql_expr:
                    continue
                alias = _m_sql_alias("snowflake", dp["derived"])
                select_parts.append(f"{sql_expr} AS {alias}")
            if select_parts:
                qual = _m_sql_table("snowflake", schema, table)
                sql = f"SELECT *, {', '.join(select_parts)} FROM {qual}"
                return [
                    "let",
                    source_line,
                    db_nav_line,
                    f'    nav = Value.NativeQuery({db_var}, "{sql}", null, [EnableFolding=true])',
                    "in",
                    "    nav",
                ], False

        # Standard table navigation: Source → Database → Schema → Table
        db_var  = f"{dbname}_Database"
        sch_var = f"{schema}_Schema"
        tbl_var = f"{table}_Table"
        base_lines = [
            "let",
            source_line,
            f'    {db_var} = Source{{[Name="{dbname}",Kind="Database"]}}[Data],',
            f'    {sch_var} = {db_var}{{[Name="{schema}",Kind="Schema"]}}[Data],',
            f'    {tbl_var} = {sch_var}{{[Name="{table}",Kind="Table"]}}[Data]',
            "in",
            f"    {tbl_var}",
        ]
        if dpc and storage_mode != "directQuery":
            base_lines, _ = _chain_add_columns(base_lines, tbl_var, dpc)
        return base_lines, False

    if conn_type == "databricks":
        server = conn.get("server", "")
        http_path = conn.get("http_path", "")
        catalog = conn.get("dbname", "")
        schema = conn.get("schema", "")
        table = conn.get("table", "")
        cat_var = f"{catalog}_Database"
        sch_var = f"{schema}_Schema"
        tbl_var = f"{table}_Table"
        return [
            "let",
            f'    Source = DatabricksMultiCloud.Catalogs("{server}", "{http_path}", [Catalog=null, Database=null, QueryTags=null, EnableAutomaticProxyDiscovery=null, Implementation="2.0"]),',
            f'    {cat_var} = Source{{[Name="{catalog}",Kind="Database"]}}[Data],',
            f'    {sch_var} = {cat_var}{{[Name="{schema}",Kind="Schema"]}}[Data],',
            f'    {tbl_var} = {sch_var}{{[Name="{table}",Kind="Table"]}}[Data]',
            "in",
            f"    {tbl_var}",
        ], False

    return [f'error "Unsupported connection type: {conn_type}"'], False


def _write_definition_pbir(report_dir: Path, model_name: str) -> None:
    """Write definition.pbir at report root referencing the SemanticModel."""
    content = {
        "version": "4.0",
        "datasetReference": {
            "byPath": {"path": f"../{model_name}.SemanticModel"}
        },
    }
    (report_dir / "definition.pbir").write_text(json.dumps(content, indent=2))


def _write_version_json(definition_dir: Path) -> None:
    """Write definition/version.json."""
    content = {
        "$schema": f"{_SCHEMA_BASE}/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0",
    }
    (definition_dir / "version.json").write_text(json.dumps(content, indent=2))


def _write_report_json(definition_dir: Path, datasource_filters: list[dict] | None = None) -> None:
    """Write definition/report.json matching PBI Desktop 2.152 format."""
    content = {
        "$schema": f"{_SCHEMA_BASE}/definition/report/3.2.0/schema.json",
        "themeCollection": {
            "baseTheme": {
                "name": "CY26SU02",
                "reportVersionAtImport": {
                    "visual": "2.6.0",
                    "report": "3.1.0",
                    "page": "2.3.0",
                },
                "type": "SharedResources",
            }
        },
        "objects": {
            "section": [
                {
                    "properties": {
                        "verticalAlignment": {
                            "expr": {"Literal": {"Value": "'Top'"}}
                        }
                    }
                }
            ]
        },
        "settings": {
            "useStylableVisualContainerHeader": True,
            "exportDataMode": "AllowSummarized",
            "defaultDrillFilterOtherVisuals": True,
            "allowChangeFilterTypes": True,
            "useEnhancedTooltips": True,
            "useDefaultAggregateDisplayName": True,
        },
    }
    if datasource_filters:
        filter_config = _build_filter_config(datasource_filters)
        if filter_config:
            content["filterConfig"] = filter_config
    (definition_dir / "report.json").write_text(json.dumps(content, indent=2))


def _write_pages(definition_dir: Path, transformed: dict) -> None:
    """Write one page folder per sheet under definition/pages/, plus pages.json manifest."""
    pages_dir = definition_dir / "pages"
    pages_dir.mkdir(exist_ok=True)

    # Group visuals by page_name (sheet), preserving insertion order
    pages: dict[str, list[dict]] = {}
    for v in transformed.get("visuals", []):
        key = v.get("page_name", v["name"])
        pages.setdefault(key, []).append(v)

    section_ids = []
    global_visual_idx = 0
    for i, (_, page_visuals) in enumerate(pages.items()):
        section_id = f"ReportSection{i + 1}"
        section_ids.append(section_id)
        page_dir = pages_dir / section_id
        page_dir.mkdir(exist_ok=True)
        _write_page(page_dir, page_visuals, global_visual_idx)
        global_visual_idx += len(page_visuals)

    _write_pages_manifest(pages_dir, section_ids)


def _write_pages_manifest(pages_dir: Path, section_ids: list[str]) -> None:
    """Write definition/pages/pages.json required by PBI Desktop for page discovery."""
    content = {
        "$schema": f"{_SCHEMA_BASE}/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": section_ids,
        "activePageName": section_ids[0] if section_ids else "",
    }
    (pages_dir / "pages.json").write_text(json.dumps(content, indent=2))


def _write_page(page_dir: Path, page_visuals: list[dict], base_visual_idx: int) -> None:
    """Write page.json and visuals for this sheet. Multiple visuals are laid out side-by-side."""
    display_name = page_visuals[0].get("page_name", page_visuals[0]["name"])
    page = {
        "$schema": f"{_SCHEMA_BASE}/definition/page/2.1.0/schema.json",
        "name": page_dir.name,
        "displayName": display_name,
        "displayOption": "FitToPage",
        "height": 720,
        "width": 1280,
    }
    (page_dir / "page.json").write_text(json.dumps(page, indent=2))

    slot = 0
    for j, visual_info in enumerate(page_visuals):
        if visual_info.get("row_fields") or visual_info.get("col_fields"):
            visuals_dir = page_dir / "visuals"
            visuals_dir.mkdir(exist_ok=True)
            visual_dir = visuals_dir / f"visual_{base_visual_idx + j + 1}"
            visual_dir.mkdir(exist_ok=True)
            _write_visual(visual_dir, visual_info, x_offset=20 + slot * 620)
            slot += 1


# Visual types that support a Series role (dimension → multiple lines/grouped bars)
_SERIES_VISUAL_TYPES = {"lineChart", "areaChart", "stackedAreaChart", "columnChart", "barChart"}

# Maps visual type to (role1, role2, shelf_for_role1, shelf_for_role2)
# shelf values: "row" or "col" — which Tableau shelf feeds each PBI role
_VISUAL_ROLES = {
    "barChart":        ("Category", "Y",    "row", "col"),
    "columnChart":     ("Category", "Y",    "col", "row"),
    "lineChart":       ("Category", "Y",    "col", "row"),
    "areaChart":       ("Category", "Y",    "col", "row"),
    "stackedAreaChart":("Category", "Y",    "col", "row"),
    "pieChart":    ("Category", "Y",        "row", "col"),
    "scatterChart":("X",        "Y",        "col", "row"),
    "map":         ("Location", "Size",     "row", "col"),
    "filledMap":   ("Location", "Size",     "row", "col"),
}


def _make_projection(default_table: str, field: dict | str, col_formats: dict | None = None) -> dict:
    """Build a field projection, using per-field table when available.

    col_formats is an optional {field_name: format_string} dict; when present a
    matching entry is written as the projection's format property.
    """
    if isinstance(field, dict):
        name = field["name"]
        field_type = "Measure" if field.get("is_measure") else "Column"
        table_name = field.get("table") or default_table
    else:
        name = field
        field_type = "Column"
        table_name = default_table
    proj: dict = {
        "field": {
            field_type: {
                "Expression": {"SourceRef": {"Entity": table_name}},
                "Property": name,
            }
        },
        "queryRef": f"{table_name}.{name}",
        "active": True,
    }
    if col_formats:
        fmt_str = col_formats.get(name, "")
        if fmt_str:
            proj["format"] = fmt_str
    return proj


def _make_series_projection(default_table: str, field: dict | str) -> dict:
    """Build a Series role projection (dimension on Color shelf → multiple lines/bars).

    Includes nativeQueryRef (field name without table prefix) which PBI Desktop writes
    for series fields to enable visual calculations referencing.
    """
    if isinstance(field, dict):
        name = field["name"]
        field_type = "Measure" if field.get("is_measure") else "Column"
        table_name = field.get("table") or default_table
    else:
        name = field
        field_type = "Column"
        table_name = default_table
    return {
        "field": {
            field_type: {
                "Expression": {"SourceRef": {"Entity": table_name}},
                "Property": name,
            }
        },
        "queryRef": f"{table_name}.{name}",
        "nativeQueryRef": name,
    }


def _make_pivot_dim_projection(default_table: str, field: dict | str) -> dict:
    """Build a pivotTable Rows/Columns projection: active=true + nativeQueryRef."""
    if isinstance(field, dict):
        name = field["name"]
        table_name = field.get("table") or default_table
    else:
        name = field
        table_name = default_table
    return {
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": table_name}},
                "Property": name,
            }
        },
        "queryRef": f"{table_name}.{name}",
        "nativeQueryRef": name,
        "active": True,
    }


def _make_pivot_measure_projection(default_table: str, field: dict | str) -> dict:
    """Build a pivotTable Values projection: nativeQueryRef only, no active flag."""
    if isinstance(field, dict):
        name = field["name"]
        table_name = field.get("table") or default_table
        field_type = "Measure" if field.get("is_measure") else "Column"
        base = field.get("base_name", name)
    else:
        name = field
        table_name = default_table
        field_type = "Column"
        base = name
    return {
        "field": {
            field_type: {
                "Expression": {"SourceRef": {"Entity": table_name}},
                "Property": name,
            }
        },
        "queryRef": f"{table_name}.{name}",
        "nativeQueryRef": base,
        "displayName": base,
    }


def _build_sort_definition(sorts: list[dict]) -> dict | None:
    """Build PBI sortDefinition from enriched sort list. Returns None if no sorts."""
    if not sorts:
        return None
    items = []
    for s in sorts:
        expr_key = "Measure" if s["is_measure"] else "Column"
        items.append({
            "field": {
                expr_key: {
                    "Expression": {"SourceRef": {"Entity": s["sort_table"]}},
                    "Property": s["sort_field"],
                }
            },
            "direction": "Ascending" if s["direction"] == "ASC" else "Descending",
        })
    return {"sort": items, "isDefaultSort": False}


def resolve_visual_type(mark_type: str, color_fields: list) -> str:
    """Return the PBI visualType string for a given Tableau mark type and color encoding.

    Area mark with a dimension on the Color shelf stacks in Tableau — PBI equivalent
    is stackedAreaChart.  All other mark types map directly via MARK_TO_VISUAL.
    """
    vtype = MARK_TO_VISUAL.get(mark_type, "tableEx")
    if vtype == "areaChart" and color_fields:
        return "stackedAreaChart"
    return vtype


def _write_visual(visual_dir: Path, visual_info: dict, x_offset: int = 20) -> None:
    """Write visual.json with role-based field projections per visual type."""
    visual_type = resolve_visual_type(
        visual_info["mark_type"], visual_info.get("color_fields", [])
    )
    table_name = visual_info["table"]
    row_fields = visual_info.get("row_fields", [])
    col_fields = visual_info.get("col_fields", [])
    color_fields = visual_info.get("color_fields", [])

    col_formats = visual_info.get("col_formats") or {}
    crosstab_measures = visual_info.get("crosstab_measures", [])
    if visual_type == "pivotTable":
        # CrossTab: row dimensions → Rows, col dimensions → Columns, measures → Values.
        # Projection structure confirmed from PBI Desktop ground truth (db_crosstab.Report).
        col_dims = [f for f in col_fields if not (f if isinstance(f, dict) else {}).get("is_measure")]
        query_state = {
            "Columns": {"projections": [_make_pivot_dim_projection(table_name, f) for f in col_dims]},
            "Rows":    {"projections": [_make_pivot_dim_projection(table_name, f) for f in row_fields]},
            "Values":  {"projections": [_make_pivot_measure_projection(table_name, f) for f in crosstab_measures]},
        }
    elif visual_type == "cardVisual":
        # Single-measure KPI card: measure comes from col_fields (text encoding), role is "Data"
        query_state = {
            "Data": {"projections": [_make_projection(table_name, f, col_formats) for f in col_fields]}
        }
    elif visual_type in _VISUAL_ROLES:
        cat_role, val_role, cat_shelf, val_shelf = _VISUAL_ROLES[visual_type]
        cat_fields = row_fields if cat_shelf == "row" else col_fields
        val_fields = col_fields if val_shelf == "col" else row_fields
        query_state = {
            cat_role: {"projections": [_make_projection(table_name, f, col_formats) for f in cat_fields]},
            val_role: {"projections": [_make_projection(table_name, f, col_formats) for f in val_fields]},
        }
        if color_fields and visual_type in _SERIES_VISUAL_TYPES:
            query_state["Series"] = {
                "projections": [_make_series_projection(table_name, f) for f in color_fields]
            }
    else:
        # tableEx and fallback: all fields under Values
        all_fields = row_fields + [f for f in col_fields if f not in row_fields]
        query_state = {
            "Values": {"projections": [_make_projection(table_name, f, col_formats) for f in all_fields]}
        }

    query: dict = {"queryState": query_state}
    sort_def = _build_sort_definition(visual_info.get("sorts", []))
    if sort_def:
        query["sortDefinition"] = sort_def

    visual_obj: dict = {"visualType": visual_type, "query": query}
    objects = _build_objects(visual_info, visual_type)
    if objects:
        visual_obj["objects"] = objects
    title_info = visual_info.get("title")
    if title_info:
        visual_obj["visualContainerObjects"] = _build_title_objects(title_info)
    container: dict = {
        "$schema": f"{_SCHEMA_BASE}/definition/visualContainer/1.0.0/schema.json",
        "name": visual_dir.name,
        "position": {"x": x_offset, "y": 20, "z": 0, "height": 360, "width": 560, "tabOrder": 0},
        "visual": visual_obj,
    }

    filter_config = _build_filter_config(visual_info.get("filters", []))
    if filter_config:
        container["filterConfig"] = filter_config

    (visual_dir / "visual.json").write_text(json.dumps(container, indent=2))


# Visual types that support axis formatting
_AXIS_VISUAL_TYPES = {"barChart", "columnChart", "lineChart", "areaChart", "stackedAreaChart", "pieChart", "scatterChart"}


def _build_objects(visual_info: dict, visual_type: str) -> dict:
    """Build the visual.objects dict from data-labels flag, color palette, and visual_format."""
    def lit(v: str) -> dict:
        return {"expr": {"Literal": {"Value": v}}}

    objects: dict = {}

    if visual_info.get("show_data_labels") and visual_type not in ("tableEx", "pivotTable"):
        objects["labels"] = [{"properties": {"show": lit("true")}}]

    color_palette = visual_info.get("color_palette", {})
    color_entity = visual_info.get("color_field_entity", "")
    color_prop = visual_info.get("color_field_property", "")
    if color_palette and color_entity and color_prop:
        dp = []
        for value, hex_color in color_palette.items():
            dp.append({
                "properties": {
                    "fill": {
                        "solid": {
                            "color": {"expr": {"Literal": {"Value": f"'{hex_color}'"}}}
                        }
                    }
                },
                "selector": {
                    "data": [
                        {
                            "scopeId": {
                                "Comparison": {
                                    "ComparisonKind": 0,
                                    "Left": {
                                        "Column": {
                                            "Expression": {"SourceRef": {"Entity": color_entity}},
                                            "Property": color_prop,
                                        }
                                    },
                                    "Right": {"Literal": {"Value": f"'{value}'"}},
                                }
                            }
                        }
                    ]
                },
            })
        objects["dataPoint"] = dp

    if visual_type == "pivotTable" and visual_info.get("crosstab_measures") and not visual_info.get("row_fields"):
        objects["values"] = [{"properties": {"valuesOnRow": lit("true")}}]
        objects["subTotals"] = [{"properties": {
            "rowSubtotals": lit("false"),
            "columnSubtotals": lit("false"),
        }}]

    fmt = visual_info.get("visual_format", {})
    if not fmt or visual_type not in _AXIS_VISUAL_TYPES:
        return objects

    raw_value_axis = fmt.get("value_axis", {})
    raw_category_axis = fmt.get("category_axis", {})
    both_title = fmt.get("both_axes_title", {})

    cat_props = _build_axis_props(raw_category_axis, both_title, lit)
    val_props = _build_axis_props(raw_value_axis, both_title, lit)

    if cat_props:
        objects["categoryAxis"] = [{"properties": cat_props}]
    if val_props:
        objects["valueAxis"] = [{"properties": val_props}]

    plot_area = fmt.get("plot_area", {})
    if plot_area.get("background_color"):
        objects["plotArea"] = [{"properties": {"color": lit(f"'{plot_area['background_color']}'")}}]

    return objects


def _build_axis_props(axis_fmt: dict, title_fmt: dict, lit) -> dict:
    """Build PBI axis formatting properties dict from parsed axis and title format dicts."""
    props: dict = {}
    if axis_fmt.get("label_font_family"):
        props["fontFamily"] = lit(f"'{axis_fmt['label_font_family']}'")
    if axis_fmt.get("label_font_size"):
        props["fontSize"] = lit(str(axis_fmt["label_font_size"]))
    if axis_fmt.get("axis_color"):
        props["axisColor"] = lit(f"'{axis_fmt['axis_color']}'")
    if axis_fmt.get("gridline_show") is not None:
        props["gridlineShow"] = lit("true" if axis_fmt["gridline_show"] else "false")
    if axis_fmt.get("gridline_style"):
        props["gridlineStyle"] = lit(f"'{axis_fmt['gridline_style']}'")
    # Axis title formatting from field-labels style-rule
    if title_fmt.get("font_family"):
        props["titleFontFamily"] = lit(f"'{title_fmt['font_family']}'")
    if title_fmt.get("font_size"):
        props["titleFontSize"] = lit(str(title_fmt["font_size"]))
    if title_fmt.get("bold"):
        props["titleBold"] = lit("true")
    return props


def _build_title_objects(title_info: dict) -> dict:
    """Build the visualContainerObjects.title block from a parsed title dict."""
    def lit(value: str) -> dict:
        return {"expr": {"Literal": {"Value": value}}}

    props: dict = {
        "show": lit("true"),
        "text": lit(f"'{title_info['text']}'"),
    }
    if "font_size" in title_info:
        props["fontSize"] = lit(str(title_info["font_size"]))
    if "font_family" in title_info:
        props["fontFamily"] = lit(f"'{title_info['font_family']}'")
    if "font_color" in title_info:
        props["fontColor"] = lit(f"'{title_info['font_color']}'")
    if "bold" in title_info:
        props["bold"] = lit("true")
    if "italic" in title_info:
        props["italic"] = lit("true")
    if "underline" in title_info:
        props["underline"] = lit("true")

    return {"title": [{"properties": props}]}
