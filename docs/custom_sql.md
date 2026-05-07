# Custom SQL Report Conversion

## Problem

Tableau supports two custom SQL datasource patterns:

1. **Single custom SQL** — one `<relation type="text">` containing a SQL query directly under the federated connection.
2. **Multiple custom SQL** — a `<relation type="collection">` containing multiple `<relation type="text">` children, each with its own SQL query and a logical relationship between them.

Both patterns were failing to convert to Power BI. The single-SQL case produced empty columns; the multi-SQL case produced an invalid M expression (`Source{[Schema="", Item=""]}[Data]`) that Power BI DirectQuery could not fold into SQL.

---

## What We Fixed

### Fix 1 — Column parsing for single custom SQL (`parser.py`)

`_parse_columns()` had no branch for `relation[@type='text']`. It fell through to the single-table fallback which looks for `./connection/relation/columns/column` — a path that does not exist for custom SQL datasources. The fix reads columns from `./metadata-records/metadata-record[@class='column']` on the connection element, which is where Tableau stores column metadata for custom SQL queries.

### Fix 2 — Table parsing for multi-SQL collections (`parser.py`)

`_parse_tables()` inside the `collection` branch only scanned for `relation[@type='table']` children (physical tables). When the children are `relation[@type='text']` (custom SQL), the result was `tables: []`. The fix adds a fallback: if no physical table children are found, scan for `type="text"` children and emit one table entry per custom SQL relation, with the SQL stored in a `custom_sql` field on the table dict.

### Fix 3 — Relationship table resolution for custom SQL (`parser.py`)

`_parse_relationships()` resolves `from_table`/`to_table` via `cols/map`, which maps `[logical_name]` → `[table].[column]`. Custom SQL collections have no `cols/map` section, so both tables came out as `""`. The fix adds a fallback: when `cols/map` is empty, build the column→table lookup from `metadata-records` `<parent-name>` elements, which record which custom SQL query each column belongs to.

### Fix 4 — Per-table custom SQL in transformer (`transformer.py`)

`_map_multi_table_sql()` built each table's connection dict from the shared datasource connection, but did not copy `custom_sql` from the per-table entry. The fix adds `"custom_sql": t.get("custom_sql", "")` to the per-table connection dict so each PBI table carries its own SQL down to the generator.

### Fix 5 — TMDL identifier quoting in relationships (`generator.py`)

The relationship writing code interpolated `from_tbl.from_col` as bare strings. This worked for simple names like `orders.order_id`, but failed when table names contained spaces (e.g. `Custom SQL Query`). The TMDL parser consumed `Custom` as the table name, hit the space, and could not parse the remainder. The fix applies `_tmdl_id()` to all four parts (`from_tbl`, `from_col`, `to_tbl`, `to_col`), which wraps names containing spaces or special characters in single quotes per the TMDL spec.

### Fix 6 — Stale TMDL table file cleanup (`generator.py`)

The generator wrote new table `.tmdl` files but never removed old ones. When a workbook was re-converted with a different table structure (e.g. from one merged table to two separate tables), leftover files from the previous run remained and caused PBI Desktop to load invalid tables. The fix clears all `.tmdl` files from the tables directory before writing new ones.

---

## Power Query M Output

Each custom SQL query becomes a separate PBI table with a `Value.NativeQuery` partition in DirectQuery mode:

```
partition 'Custom SQL Query' = m
    mode: directQuery
    source = ```
        let
            Source = Sql.Database("server", "database"),
            nav = Value.NativeQuery(Source, "SELECT ...", null, [EnableFolding=true])
        in
            nav
        ```
```

The triple-backtick `source = ``` ` syntax is required because the multi-line SQL string would violate TMDL indentation rules if written inline. This is documented in the TMDL spec: *"Everything between three backticks is considered part of the multi-block expression and TMDL indentation rules aren't applied."*

---

## Relationship Output

Relationships between custom SQL tables are written to `relationships.tmdl` with quoted identifiers:

```
relationship 'Custom SQL Query_CustomerID -> Custom SQL Query1_CustomerID (Orders)'
    fromColumn: 'Custom SQL Query'.CustomerID
    toColumn: 'Custom SQL Query1'.'CustomerID (Orders)'
```

---

## Supported Patterns

| Pattern | Example | Supported |
|---------|---------|-----------|
| Single custom SQL, any SQL database | `sql_custom_single.twb` | Yes |
| Multiple custom SQL with relationship, any SQL database | `sql_custom_rds.twb` | Yes |
| Custom SQL on non-SQL sources (Excel, CSV) | — | No — flagged as unsupported |

All SQL-capable connectors are supported: PostgreSQL, SQL Server, MySQL, Redshift, Snowflake, Oracle, BigQuery.
