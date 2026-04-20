"""Translate Tableau calculated field formulas to DAX using Claude."""

import os
import anthropic

_CLIENT: anthropic.Anthropic | None = None

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
- If the formula uses Tableau LOD expressions ({fixed}, {include}, {exclude}), Parameters ([Parameters].*), cross-datasource references ([federated.*]), table calculations (INDEX(), RANK(), RUNNING_SUM()), or any construct with no DAX equivalent, return exactly: UNSUPPORTED
- Do not add DEFINE MEASURE or variable wrappers unless needed."""


def _client() -> anthropic.Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _CLIENT


def translate_formula(formula: str, table_name: str) -> tuple[str, str]:
    """Translate a Tableau formula to DAX.

    Returns (dax_expression, status) where status is 'translated' or 'unsupported'.
    """
    prompt = f"Table name: {table_name}\nTableau formula: {formula}"
    msg = _client().messages.create(
        model="claude-opus-4-7",
        max_tokens=256,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    result = msg.content[0].text.strip()
    if result.upper() == "UNSUPPORTED":
        return "", "unsupported"
    return result, "translated"


def translate_calc_fields_in_transformed(transformed: dict) -> dict:
    """Run AI translation on pending calc fields. Returns updated transformed dict."""
    report = transformed.get("report", {})
    calc_fields = report.get("calculated_fields", [])
    if not calc_fields:
        return transformed

    measures = {(m["table"], m["name"]): m for m in transformed.get("measures", [])}
    updated_cfs = []
    for cf in calc_fields:
        table_name = cf.get("table") or (transformed.get("tables") or [{}])[0].get("name", "")
        dax, status = translate_formula(cf["formula"], table_name)
        updated_cf = {**cf, "status": status}
        if status == "translated" and dax:
            updated_cf["dax"] = dax
            measures[(table_name, cf["name"])] = {"name": cf["name"], "table": table_name, "dax": dax}
        updated_cfs.append(updated_cf)

    return {
        **transformed,
        "measures": list(measures.values()),
        "report": {**report, "calculated_fields": updated_cfs},
    }
