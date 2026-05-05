"""Translate Tableau calculated field formulas to DAX using Claude."""

import os
import re
import anthropic

_CLIENT: anthropic.Anthropic | None = None

_DIRECTQUERY_BLOCKLIST = {
    "MEDIAN", "PERCENTILE.INC", "PERCENTILE.EXC", "PERCENTILE",
    "PATH", "PATHITEM", "PATHITEMREVERSE", "PATHLENGTH", "PATHCONTAINS",
    "DATATABLE", "ROLLUPADDISSUBTOTAL", "ROLLUPGROUP",
    "TOPNSKIP",
}

_SYSTEM = """You are a Tableau-to-DAX formula translator.
Given a Tableau calculated field formula and the Power BI table name that contains the columns, translate it to a valid DAX measure expression.

Rules:
- Return ONLY the DAX expression — no explanation, no markdown, no code fences.
- Use 'TableName'[ColumnName] syntax for column references.
- Replace Tableau aggregations: SUM→SUM, AVG→AVERAGE, COUNTD→DISTINCTCOUNT, COUNT→COUNTA, MIN→MIN, MAX→MAX, MEDIAN→MEDIAN.
- Replace DATEDIFF('day', a, b) → DATEDIFF("DAY", a, b).
- Replace IF/ELSEIF/ELSE/END → IF(..., ..., ...) or nested IF in DAX.
- Replace CASE/WHEN/THEN/ELSE/END → SWITCH(TRUE(), ...).
- Replace string literals as-is.
- For simple field references like [Field] → 'TableName'[Field].

Row-level calculations (arithmetic on bare column references with no explicit aggregation):
- NEVER write 'Table'[Column] directly in a measure — it causes "cannot determine a single value" errors in Power BI because a measure has no row context.
- When a Tableau formula multiplies, divides, adds, or subtracts bare column references (e.g. [Quantity] * [Price]), it is a row-level calculation. Wrap it in SUMX over the primary table.
- Pattern: SUMX('PrimaryTable', 'PrimaryTable'[col1] * RELATED('OtherTable'[col2]))
- Use RELATED() for columns that come from a related lookup table (the one-side of the relationship).
- Example: [Quantity] * [Price] where Quantity is in OrderItems (fact) and Price is in Products (lookup) → SUMX(OrderItems, OrderItems[Quantity] * RELATED(Products[Price]))

LOD expressions:
- {FIXED [d1], [d2] : AGG([m])} → CALCULATE(AGG('TableName'[m]), ALLEXCEPT('TableName', 'TableName'[d1], 'TableName'[d2]))
- {FIXED : AGG([m])} (no dims) → CALCULATE(AGG('TableName'[m]), ALL('TableName'))
- {INCLUDE [d] : AGG([m])} → CALCULATE(AGG('TableName'[m]), VALUES('TableName'[d]))
- {EXCLUDE [d] : AGG([m])} → CALCULATE(AGG('TableName'[m]), ALL('TableName'[d]))

- If the formula uses Parameters ([Parameters].*), cross-datasource references ([federated.*]), or table calculations (INDEX(), SIZE()), return exactly: UNSUPPORTED
- Do not add DEFINE MEASURE or variable wrappers unless needed."""


_COLUMN_REF_RE = re.compile(r"'[^']+'\[[^\]]+\]")
_AGG_RE = re.compile(
    r'\b(SUM|SUMX|AVERAGE|AVERAGEX|DISTINCTCOUNT|COUNTA|COUNT|MIN|MINX|MAX|MAXX|MEDIAN|MEDIANX|CALCULATE)\s*\(',
    re.IGNORECASE,
)


def _has_bare_column_reference(dax: str) -> bool:
    """Return True if DAX has 'Table'[Column] references with no aggregation function.

    Catches the pattern where Claude emits bare column multiplication like
    'T1'[A] * 'T2'[B] which is invalid in a measure context.
    """
    return bool(_COLUMN_REF_RE.search(dax)) and not bool(_AGG_RE.search(dax))


def _client() -> anthropic.Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _CLIENT


_DQ_CONSTRAINT = (
    "\nIMPORTANT: This measure will run in DirectQuery mode. "
    "Only use DAX functions compatible with DirectQuery. "
    "Do NOT use MEDIAN, PERCENTILE, PATH functions, DATATABLE, or time intelligence "
    "functions on non-date tables. If the formula requires any of these, return UNSUPPORTED."
)


def _blocklist_check(dax: str) -> bool:
    """Return True if dax contains a DirectQuery-incompatible function."""
    upper = dax.upper()
    return any(fn + "(" in upper for fn in _DIRECTQUERY_BLOCKLIST)


def translate_formula(
    formula: str,
    table_name: str,
    columns: list[str] | None = None,
    directquery: bool = False,
    all_tables: dict[str, list[str]] | None = None,
) -> tuple[str, str]:
    """Translate a Tableau formula to DAX.

    Returns (dax_expression, status) where status is 'translated', 'unsupported',
    or 'unsupported_directquery'.
    """
    system = _SYSTEM + (_DQ_CONSTRAINT if directquery else "")
    col_hint = f"\nPrimary table columns: {', '.join(columns)}" if columns else ""
    related_hint = ""
    if all_tables and len(all_tables) > 1:
        others = {t: cols for t, cols in all_tables.items() if t != table_name}
        related_hint = "\nRelated tables: " + "; ".join(
            f"{t}[{', '.join(cols)}]" for t, cols in others.items()
        )
        related_hint += (
            "\nNote: Tableau disambiguates duplicate column names with a (TableName) suffix, "
            "e.g. [order_id (returns)] refers to the 'order_id' column in the 'returns' table."
        )
    prompt = f"Table name: {table_name}{col_hint}{related_hint}\nTableau formula: {formula}"
    msg = _client().messages.create(
        model="claude-opus-4-7",
        max_tokens=256,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    result = msg.content[0].text.strip()
    if result.upper() == "UNSUPPORTED":
        return "", "unsupported"
    if directquery and _blocklist_check(result):
        return "", "unsupported_directquery"

    # Option 1 — static check: detect bare column references with no aggregation
    if _has_bare_column_reference(result):
        # Option 5 — ask Claude to self-correct with the specific error identified
        correction = (
            f"The DAX you returned has bare column references that will cause "
            f"'cannot determine a single value' errors in Power BI:\n{result}\n"
            f"A DAX measure has no row context. Use SUMX over the primary table "
            f"and RELATED() for columns from related tables.\n"
            f"Table name: {table_name}{col_hint}{related_hint}\n"
            f"Tableau formula: {formula}\n"
            f"Return only the corrected DAX expression."
        )
        msg2 = _client().messages.create(
            model="claude-opus-4-7",
            max_tokens=256,
            system=system,
            messages=[{"role": "user", "content": correction}],
        )
        result = msg2.content[0].text.strip()
        if result.upper() == "UNSUPPORTED":
            return "", "unsupported"

    return result, "translated"


def _substitute_calc_names(formula: str, calc_name_map: dict[str, str]) -> str:
    """Replace [Calculation_xxx] tokens with display names before sending to Claude."""
    for internal, display in calc_name_map.items():
        formula = formula.replace(f"[{internal}]", f"[{display}]")
    return formula


def translate_calc_fields_in_transformed(transformed: dict) -> dict:
    """Run AI translation on pending calc fields. Returns updated transformed dict."""
    report = transformed.get("report", {})
    calc_fields = report.get("calculated_fields", [])
    if not calc_fields:
        return transformed

    # Build column list per table for context
    columns_by_table: dict[str, list[str]] = {}
    for t in transformed.get("tables", []):
        columns_by_table[t["name"]] = [c["name"] for c in t.get("columns", [])]

    # Identify which tables use DirectQuery
    dq_tables = {
        t["name"]
        for t in transformed.get("tables", [])
        if t.get("connection", {}).get("storage_mode") == "directQuery"
    }

    calc_name_map = transformed.get("calc_name_map", {})

    measures = {(m["table"], m["name"]): m for m in transformed.get("measures", [])}
    updated_cfs = []
    for cf in calc_fields:
        table_name = cf.get("table") or (transformed.get("tables") or [{}])[0].get("name", "")
        columns = columns_by_table.get(table_name)
        is_dq = table_name in dq_tables
        formula = _substitute_calc_names(cf["formula"], calc_name_map)
        dax, status = translate_formula(formula, table_name, columns, directquery=is_dq, all_tables=columns_by_table)
        updated_cf = {**cf, "status": status}
        if status == "translated" and dax:
            updated_cf["dax"] = dax
            measures[(table_name, cf["name"])] = {"name": cf["name"], "table": table_name, "dax": dax}
        updated_cfs.append(updated_cf)

    unsupported_names = {cf["name"] for cf in updated_cfs if cf["status"] != "translated"}
    updated_visuals = []
    pruned_sort_warnings: list[str] = []
    for v in transformed.get("visuals", []):
        pruned_sorts = []
        for s in v.get("sorts", []):
            if s.get("is_measure") and s.get("sort_field") in unsupported_names:
                pruned_sort_warnings.append(
                    f"Sort by '{s['sort_field']}' removed: calc field translation unsupported"
                )
            else:
                pruned_sorts.append(s)
        updated_visuals.append({
            **v,
            "row_fields": [f for f in v.get("row_fields", []) if f.get("name") not in unsupported_names],
            "col_fields": [f for f in v.get("col_fields", []) if f.get("name") not in unsupported_names],
            "sorts": pruned_sorts,
        })

    updated_unsupported = report.get("unsupported", []) + pruned_sort_warnings
    return {
        **transformed,
        "measures": list(measures.values()),
        "visuals": updated_visuals,
        "report": {**report, "calculated_fields": updated_cfs, "unsupported": updated_unsupported},
    }
