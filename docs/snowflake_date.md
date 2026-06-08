# Snowflake DirectQuery + Date Part Columns — RCA & Fix Plan

## Problem

`snowflkake.twb` has a Tableau shelf field `yr:O_ORDERDATE` which the transformer emits as a `date_part_columns` (dpc) entry on the ORDERS table. The generator must add an `O_ORDERDATE Year` derived column to the M partition so the TMDL `sourceColumn: O_ORDERDATE Year` resolves correctly in DirectQuery.

---

## Error History

### Error 1 — Fixed
`[Expression.Error] The key didn't match any rows in the table`
- Cause: wrong 2nd arg to `Snowflake.Databases` (dbname instead of warehouse) + wrong navigation pattern
- Fix: dedicated Snowflake branch with correct 3-level navigation and `warehouse` from TWB XML

### Error 2 — Fix attempted, caused Error 3
`[Expression.Error] The name 't1.O_ORDERDATE Year' doesn't exist in the current context`
- Cause: dpc path not handled; TMDL declared `sourceColumn: O_ORDERDATE Year` but M returned raw table
- Fix attempted: `Value.NativeQuery(schema_var, "SELECT *, YEAR(O_ORDERDATE) AS ...", null, [EnableFolding=true])` but kept `[Implementation="2.0"]` (ADBC) on the connection

### Error 3 — Current broken state
`[Expression.Error] Native queries aren't supported by this value`
- Cause: `[Implementation="2.0"]` selects the Arrow Database Connectivity (ADBC) driver. ADBC does NOT expose `NativeQuery.Supported` capability. `Value.NativeQuery` requires that capability on its target value.
- Impact: ALL sheets on ORDERS table broken (Sheet 1 and Sheet 3), not just the dpc one

---

## Root Cause

`Snowflake.Databases(..., [Implementation="2.0"])` (ADBC) and `Value.NativeQuery` are mutually exclusive:

| Driver | `Value.NativeQuery` | `Table.AddColumn` (DirectQuery) |
|--------|--------------------|---------------------------------|
| ADBC (`[Implementation="2.0"]`) | NOT supported | Breaks query folding |
| ODBC (no `[Implementation]` option) | Supported | Breaks query folding |

`Table.AddColumn` was also evaluated and rejected — Microsoft community documentation confirms it breaks query folding for Snowflake DirectQuery, so derived columns would not fold to SQL.

---

## Official Documentation Backing

1. **`Value.NativeQuery + EnableFolding=true` on Snowflake is officially supported**
   Source: [Microsoft — Query folding on native queries](https://learn.microsoft.com/en-us/power-query/native-query-folding)
   Snowflake is explicitly listed as a supported connector.

2. **Removing `[Implementation="2.0"]` is Microsoft's documented self-mitigation**
   Source: Microsoft Power BI Snowflake connector docs — "If features aren't available, remove `Implementation=2.0` to fall back to the ODBC-based connector."

3. **Snowflake SQL for date parts**: `YEAR(col)`, `MONTH(col)`, `QUARTER(col)`, `WEEKOFYEAR(col)`, `DAY(col)`, `HOUR(col)`, `MINUTE(col)`, `SECOND(col)`
   Source: [Snowflake date & time functions](https://docs.snowflake.com/en/sql-reference/functions-date-time)

---

## Fix Plan

### Datasource-level implementation flag

All tables in a single Snowflake datasource must use the same `Snowflake.Databases` call (PBI groups by `(server, warehouse)`). Mixing ADBC/ODBC = separate connection identities = separate credentials prompt.

**Rule**: if ANY table in the datasource has `date_part_columns` → use ODBC for ALL tables of that datasource.

### M expression logic (in `generator.py` Snowflake branch)

```
has_dpc = bool(dpc)  # dpc = date_part_columns for this table

if has_dpc or datasource_has_any_dpc:
    # ODBC path — supports Value.NativeQuery
    src = Snowflake.Databases(server, warehouse)   # no [Implementation="2.0"]
else:
    # ADBC path — preferred modern driver when NativeQuery not needed
    src = Snowflake.Databases(server, warehouse, [Implementation="2.0"])
```

For dpc tables (ODBC path):
```m
let
    Source = Snowflake.Databases("server", "warehouse"),
    DB = Source{[Name="DB", Kind="Database"]}[Data],
    Schema = DB{[Name="SCHEMA", Kind="Schema"]}[Data],
    nav = Value.NativeQuery(Schema, "SELECT *, YEAR(O_ORDERDATE) AS ""O_ORDERDATE Year"" FROM ""ORDERS""", null, [EnableFolding=true])
in
    nav
```

For non-dpc tables in same datasource (also ODBC, same connection identity):
```m
let
    Source = Snowflake.Databases("server", "warehouse"),
    DB = Source{[Name="DB", Kind="Database"]}[Data],
    Schema = DB{[Name="SCHEMA", Kind="Schema"]}[Data],
    Table = Schema{[Name="TABLE", Kind="Table"]}[Data]
in
    Table
```

### Where to implement

- `tab_to_pbi/generator.py` — Snowflake branch in `_build_m_expression()`
- The `datasource_has_any_dpc` flag must be passed in from the caller (or computed from all tables in the same datasource before generating M expressions)
- `_DATE_PART_SQL["snowflake"]` dict already has all Snowflake SQL templates — no changes needed there
- `_m_sql_alias("snowflake", derived)` already handles double-quoting aliases — no changes needed there

---

## Files to Change

| File | Change |
|------|--------|
| `tab_to_pbi/generator.py` | Snowflake branch: pass `use_odbc` flag; omit `[Implementation="2.0"]` when true; `Value.NativeQuery` at schema level for dpc tables |
| `tab_to_pbi/generator.py` (caller) | Compute `datasource_has_any_dpc` before iterating tables; pass to `_build_m_expression` |

No changes needed in `parser.py` or `transformer.py`.
