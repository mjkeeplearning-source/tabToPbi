# Date Part Column & Hierarchy Implementation

## Problem

Tableau auto-creates date granularity when a date field is placed on a shelf. A shelf token like `yr:order_date:ok` means "Year of Order Date". The pipeline previously stripped the prefix and bound the raw `order_date` datetime column to the visual — PBI showed individual dates instead of year-grouped values.

PBI Desktop 2.152 does not support TMDL calculated columns (`expression` on `column` objects), so DAX-based derived columns are blocked.

## Solution

Date-part columns are injected at the **Power Query M layer** — as physical columns in the query result rather than DAX calculated columns. This works for both Import and DirectQuery storage modes.

## Data Flow

```
Tableau shelf: yr:order_date:ok
       ↓ parser.py  (unchanged)
{name: "order_date", date_part: "YEAR"}
       ↓ transformer.py  _resolve_field()
{name: "order_date Year", is_measure: False, table: "orders"}
  + accumulates: orders.date_part_columns = [{base_col: "order_date", part: "YEAR", derived: "order_date Year"}]
       ↓ generator.py  _build_m_expression()
  Import:     Table.AddColumn(prev, "order_date Year", each Date.Year([#"order_date"]), Int64.Type)
  DirectQuery: Value.NativeQuery(Source, "SELECT *, EXTRACT(YEAR FROM order_date) AS ""order_date Year"" FROM ...")
       ↓ generator.py  _write_tmdl_table()
  column 'order_date Year'
      dataType: int64
      sourceColumn: order_date Year
  (+ hierarchy block when 2+ parts from same base column)
       ↓ visual.json  _make_projection()  (no change needed)
  "Property": "order_date Year"   ← was "order_date"
```

## Files Changed

| File | Change |
|------|--------|
| `parser.py` | `_parse_filter_element` now extracts `date_part` prefix from filter column attributes so date-part filters bind to derived columns |
| `transformer.py` | `_resolve_field` returns derived column name (`order_date Year`) and accumulates per-table requirements; `_process_sheets` wires the accumulator through all field resolution calls, remaps filter fields, and attaches `date_part_columns` to each table dict |
| `generator.py` | `_DATE_PART_SQL` (9 connectors), `_DATE_PART_M` (8 parts), `_chain_add_columns`, `_m_sql_alias`, `_m_sql_table` helpers; `_build_m_expression` injects derived columns; `_write_tmdl_table` writes derived columns + hierarchy block |

## SQL Dialect Lookup (`_DATE_PART_SQL`)

Per-dialect SQL for 9 connectors, sourced from official vendor documentation:

| Part | Postgres/Redshift | MySQL | SQL Server | Snowflake | BigQuery | Oracle | Teradata |
|------|-------------------|-------|------------|-----------|----------|--------|----------|
| YEAR | `EXTRACT(YEAR FROM c)` | `YEAR(c)` | `YEAR(c)` | `YEAR(c)` | `EXTRACT(YEAR FROM c)` | `EXTRACT(YEAR FROM c)` | `EXTRACT(YEAR FROM c)` |
| QUARTER | `EXTRACT(QUARTER FROM c)` | `QUARTER(c)` | `DATEPART(quarter,c)` | `QUARTER(c)` | `EXTRACT(QUARTER FROM c)` | `TO_NUMBER(TO_CHAR(c,'Q'))` | `CAST((EXTRACT(MONTH FROM c)+2)/3 AS INTEGER)` |
| MONTH | `EXTRACT(MONTH FROM c)` | `MONTH(c)` | `MONTH(c)` | `MONTH(c)` | `EXTRACT(MONTH FROM c)` | `EXTRACT(MONTH FROM c)` | `EXTRACT(MONTH FROM c)` |
| WEEKNUM | `EXTRACT(WEEK FROM c)` | `WEEK(c)` | `DATEPART(week,c)` | `WEEKOFYEAR(c)` | `EXTRACT(WEEK FROM c)` | `TO_NUMBER(TO_CHAR(c,'IW'))` | `TD_WEEK_OF_YEAR(c)` |
| DAY | `EXTRACT(DAY FROM c)` | `DAY(c)` | `DAY(c)` | `DAY(c)` | `EXTRACT(DAY FROM c)` | `EXTRACT(DAY FROM c)` | `EXTRACT(DAY FROM c)` |

## M Function Lookup (`_DATE_PART_M`) — Import Mode

| Part | M Expression | Output Type |
|------|-------------|-------------|
| YEAR | `Date.Year([#"col"])` | `Int64.Type` |
| QUARTER | `Date.QuarterOfYear([#"col"])` | `Int64.Type` |
| MONTH | `Date.Month([#"col"])` | `Int64.Type` |
| WEEKNUM | `Date.WeekOfYear([#"col"])` | `Int64.Type` |
| DAY | `Date.Day([#"col"])` | `Int64.Type` |
| HOUR | `Time.Hour([#"col"])` | `Int64.Type` |
| MINUTE | `Time.Minute([#"col"])` | `Int64.Type` |
| SECOND | `Time.Second([#"col"])` | `Int64.Type` |

## Compound Labels (2021 Q1, 2021 Q1 W1)

When multiple date-parts from the same base column appear on the same shelf (e.g. `yr:order_date` and `qr:order_date`), the transformer accumulates both in `date_part_columns`. The generator emits:

1. Individual columns: `order_date Year` (int64) and `order_date Quarter` (int64)
2. A TMDL `hierarchy` block grouping them in canonical order (YEAR → QUARTER → MONTH → WEEK → DAY → HOUR → MINUTE → SECOND)
3. Two `Column` projections in the visual's axis role

PBI Desktop renders compound axis labels (`2021 Q1`, `2021 Q2`) natively when multiple columns from a hierarchy are placed on the same visual axis.

## DirectQuery Behaviour

For DirectQuery SQL sources, `Value.NativeQuery(..., [EnableFolding=true])` is used. `EnableFolding=true` preserves PBI's ability to push additional filters/slicers as SQL WHERE clauses on top of the expanded SELECT — same pattern already used by the custom SQL path.

## Teradata Note

`WEEKNUM` for Teradata uses `TD_WEEK_OF_YEAR(col)`, which requires `TD_SYSFNLIB` to be installed on the Teradata instance. All other Teradata date parts use standard ANSI `EXTRACT`.

## Scope

The new code path fires **only** when a parsed shelf field or filter has a non-null `date_part` key. Workbooks with no date-part shelf encodings (`yr:`, `qr:`, `mn:`, etc.) are completely unaffected — all 120 unit tests and all 5 existing input workbooks continue to pass with 0 errors.
