# AI in TabToPBI: How Claude Solves the Hard Part

## The Core Problem

Migrating a Tableau workbook to Power BI is mostly mechanical: parse XML, map visual types, write M expressions. The pipeline handles all of that deterministically.

One part is not mechanical: **Tableau calculated field formulas**.

Tableau uses its own formula language (TWF). Power BI uses DAX. The two languages differ in:

- **Syntax** — `IF/ELSEIF/ELSE/END` vs nested `IF()`, `CASE/WHEN` vs `SWITCH(TRUE(),…)`
- **Aggregation semantics** — Tableau aggregates implicitly at the view level; DAX measures require explicit aggregation with row-context awareness
- **LOD (Level of Detail) expressions** — Tableau has `{FIXED}`, `{INCLUDE}`, `{EXCLUDE}`; DAX uses `CALCULATE` with filter modifiers (`ALLEXCEPT`, `VALUES`, `ALL`)
- **Row-level vs measure context** — Tableau arithmetic like `[Quantity] * [Price]` works on rows automatically; in DAX the same expression inside a measure causes a "cannot determine a single value" error and must be rewritten as `SUMX`

Writing a deterministic rule-based translator for TWF → DAX is possible for simple cases but breaks down quickly:

- LOD syntax requires understanding filter semantics, not just syntax substitution
- Cross-table formula references require knowing which columns come from which tables (and Tableau uses disambiguation suffixes like `[order_id (returns)]`)
- Conditional logic can nest arbitrarily
- Edge cases (Parameters, table calcs, cross-datasource refs) must be detected and excluded, not mistranslated

**This is the exact class of problem where an LLM provides leverage**: the translation space is large but well-defined, the input/output format is structured, and errors are detectable.

---

## How Claude Is Used

### Entry point

`translator.py` → `translate_formula()` is called once per calculated field via `translate_calc_fields_in_transformed()` in `main.py`, after the deterministic transform pass is complete.

Claude model used: `claude-haiku-4-5` (direct API) or `claude-opus-4-5` (Bedrock).

### What the prompt contains

Each API call includes:

1. **A system prompt** — hard rules: return only DAX, no markdown, use `'TableName'[Col]` syntax, specific patterns for LOD, SUMX, RELATED, SWITCH, etc.
2. **Primary table name** — exact PBI table name to use in references
3. **Column list for the primary table** — so Claude resolves `[FieldName]` to the correct table
4. **Related table columns** — when the datasource has multiple tables, all other tables and their columns are included, plus a note explaining Tableau's disambiguation suffix convention
5. **The Tableau formula** — with internal `Calculation_xxx` IDs already substituted with display names (see below)

```python
prompt = f"Table name: {table_name}{col_hint}{related_hint}{table_hint}\nTableau formula: {formula}"
```

### What Claude returns

Either a valid DAX expression (e.g. `CALCULATE(SUM('orders'[profit]), ALLEXCEPT('orders', 'orders'[order_id]))`) or the literal string `UNSUPPORTED`.

Fields marked `UNSUPPORTED` are excluded from the TMDL semantic model and logged in `migration_report.json`.

---

## Specific Problems Claude Solves That Would Be Hard Otherwise

### 1. LOD Expressions

Tableau LOD syntax has no direct DAX equivalent — it requires understanding filter semantics:

| Tableau | DAX |
|---------|-----|
| `{FIXED [Order ID] : SUM([Profit])}` | `CALCULATE(SUM('orders'[profit]), ALLEXCEPT('orders', 'orders'[order_id]))` |
| `{INCLUDE [Region] : AVG([Sales])}` | `CALCULATE(AVERAGE('orders'[sales]), VALUES('orders'[region]))` |
| `{EXCLUDE [Category] : SUM([Sales])}` | `CALCULATE(SUM('orders'[sales]), ALL('orders'[category]))` |

A regex-based translator could handle fixed patterns, but LOD expressions can have multiple dimensions, nested expressions, and mixed aggregations. Claude handles the full variety.

### 2. Cross-Table Formula References

`DeltaOrder = COUNTD([order_id]) - COUNTD([order_id (returns)])`

The field `order_id (returns)` is Tableau's disambiguated name for `order_id` from the `returns` table. To translate this correctly, the translator must know:
- both `orders` and `returns` tables exist
- `order_id (returns)` is the `order_id` column in `returns`
- the correct DAX is `DISTINCTCOUNT('orders'[order_id]) - DISTINCTCOUNT('returns'[order_id])`

This context is injected as `related_hint` in the prompt. Without it, Claude cannot resolve which table the ambiguous column belongs to.

### 3. Internal Calc ID Substitution (Pre-processing)

Tableau internally names calculated fields as `Calculation_1234567`. Formulas that reference other calc fields use these internal IDs, not display names:

```
[Calculation_5678] > [Calculation_9012]
```

Before sending to Claude, `_substitute_calc_names()` replaces all `[Calculation_xxx]` tokens with their display names using the `calc_name_map` built during parsing:

```
[Days to Ship Actual] > [Days to Ship Scheduled]
```

This is critical: without it, Claude returns syntactically valid DAX that references non-existent measures, and PBI Desktop fails to open the file.

### 4. Row-Context Detection and Self-Correction

DAX measures run in filter context, not row context. A common Claude failure mode is emitting bare column multiplication:

```dax
'orders'[Quantity] * 'products'[Price]   -- invalid in a measure
```

The pipeline detects this via `_has_bare_column_reference()` (regex: any `'T'[C]` reference with no surrounding aggregation function), then issues a second API call with a targeted correction prompt:

```
The DAX you returned has bare column references that will cause
'cannot determine a single value' errors in Power BI:
<original DAX>
A DAX measure has no row context. Use SUMX over the primary table
and RELATED() for columns from related tables.
Return only the corrected DAX expression.
```

This self-correction loop catches a class of errors that a pure static validator cannot fix — only regeneration can.

---

## Defense in Depth for DirectQuery

When a datasource is a live SQL connection (no Tableau extract), the pipeline sets `storage_mode: directQuery`. DAX for DirectQuery has restrictions — functions like `MEDIAN`, `PATH`, `DATATABLE`, and time intelligence on non-date tables are unsupported.

Two layers handle this:

**Layer 1 — Prompt constraint**: when `directquery=True`, the system prompt appends an explicit instruction telling Claude to restrict output to DirectQuery-compatible DAX and return `UNSUPPORTED` if the formula requires an incompatible function.

**Layer 2 — Static blocklist**: after Claude responds, `_blocklist_check()` scans the result for banned function names (`MEDIAN(`, `PATH(`, `DATATABLE(`, etc.). If found, the field is marked `unsupported_directquery` regardless of what Claude returned.

Either layer alone can fail: Claude can hallucinate a compatible-looking expression that uses a banned function; the blocklist cannot catch subtle semantic incompatibilities. Both together provide the required reliability.

---

## What Is Deliberately NOT AI

Everything else in the pipeline is deterministic:

| Task | Approach |
|------|----------|
| Parse `.twb` XML | `lxml` / stdlib ElementTree |
| Visual type mapping (Bar → barChart) | Static dict `MARK_TO_VISUAL` |
| Aggregation decoding (sum: → SUM) | Static dict `_AGG_LABEL` |
| Power Query M expression generation | Template strings per connector type |
| Relationship cardinality inference | Join-type + naming convention heuristics |
| Filter migration | Deterministic field mapping + operator table |
| PBIR file structure | String templates / JSON writes |

AI is used only where the translation space is too large for deterministic rules and where errors are detectable (DAX syntax, `UNSUPPORTED` sentinel).

---

## Summary

Claude solves the formula translation problem that sits at the core of the Tableau → Power BI migration:

- **Without Claude**: users must manually rewrite every calculated field in DAX — typically 10–50+ fields per workbook, requiring deep knowledge of both languages.
- **With Claude**: formulas are translated automatically with full context (table structure, cross-table relationships, LOD semantics), with a self-correction loop for row-context errors and a deterministic blocklist for DirectQuery safety.

The pipeline is structured so Claude is a narrow, well-constrained translator — not a reasoning agent. Inputs are structured, outputs are validated, and failures produce explicit `UNSUPPORTED` entries in the migration report rather than silent errors.
