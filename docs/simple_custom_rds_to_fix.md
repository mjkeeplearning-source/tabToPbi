# sql_custom_rds Sheet 3 — Data Mismatch Issue

## Symptom

Sheet 3 in `sql_custom_rds.twb`: `CNT(Orders)` grouped by `CustomerName`.
- Tableau shows **200** per customer (correct, filtered per customer)
- PBI shows **1000** per customer (wrong, total row count — no filter applied)

## Root Cause

Three-layer chain:

1. **Tableau XML has no cardinality.** Object-graph relationship XML has `first-end-point` / `second-end-point` only. No `cardinality` attribute exists in any of our workbooks. This is by design — Tableau's runtime query engine infers direction dynamically; it never needs it stored.

2. **Transformer blindly passes first-end-point as `from_table`.** In `_map_relationship()` (`transformer.py:213`), logical relationships (no `join_type`) are returned as-is with no cardinality set. For `sql_custom_rds`, Tableau placed Customers (ONE side) as `first-end-point` — so `from_table = Customers`.

3. **Generator defaults to assuming `from = MANY` (wrong here).** Generator reads `from_cardinality` default `"many"`, writes `fromColumn: 'Custom SQL Query'.CustomerID` (Customers) and `toColumn: 'Custom SQL Query1'.'CustomerID (Orders)'` (Orders). In TMDL, default `oneDirection` filter flows from `toColumn`'s table (Orders) → `fromColumn`'s table (Customers). CustomerName filter never reaches Orders → `COUNTROWS` returns 1000.

**Why `simple_join` is unaffected:** Tableau happened to place `orders` (MANY side) as `first-end-point` — correct by accident. No bug manifests.

## Fundamental Gap

Tableau uses a runtime query model (computes join direction from shelf context and data). Power BI uses a static model (direction declared at design time). The Tableau XML provides no direction signal because Tableau's engine never needed one stored. Any fix is a heuristic, not derivable from the spec.

## Options

### Option A — Signal 1 with object captions (recommended)

Apply the existing `_col_matches_table` naming heuristic (already used for physical joins) to logical relationships, using object-graph **captions** (`Customers`, `Orders`) instead of physical query names (`Custom SQL Query`).

- Strip disambiguation suffix `(TableName)` from column before matching
- `CustomerID` vs caption `Customers` → base `customer` = tname `customer` → **fires** → Customers = ONE → swap from/to → correct TMDL direction
- When signal silent: keep current ordering + emit `relationship_cardinality_warnings` in migration report
- Requires updating Case 1 in `docs/relationship.md` (currently says "no inference")

**Impact on existing workbooks:**

| Workbook | Signal fires? | Effect |
|---|---|---|
| `sql_custom_rds.twb` | Yes | Direction corrected — Sheet 3 data matches Tableau |
| `simple_join.twb` | No (snake_case `order_id`/`orders`) | Unchanged, already correct |
| `simple_join_calculated_line.twb` people↔orders | No (`region`/`people`) | Unchanged + warning in report |
| All others | N/A (no logical rels) | Zero impact |

**Limitation:** Heuristic only — works for PascalCase PK naming (`CustomerID`/`Customers`, `ProductID`/`Products`). Silent for snake_case or unrelated names. Not backed by official spec.

### Option B — `crossFilteringBehavior: bothDirections` on all logical relationships

Add `bothDirections` to every logical relationship regardless of cardinality.

- Fixes all cases including where Signal 1 is silent
- Microsoft documentation explicitly warns: can cause ambiguous filter paths in models with multiple relationships
- `simple_join_calculated_line` has 2 relationships — not safe by documentation for this workbook
- Broad claim "safe for all" is not backed by official docs

### Option C — Warning only (no direction fix)

Emit `relationship_cardinality_warnings` for all logical relationships. User fixes direction manually in PBI Desktop Model View.

- Honest about the limitation
- Does not fix the data mismatch automatically

## Files to change (Option A)

- `tab_to_pbi/parser.py` — store caption in `object_id_map` alongside physical table name
- `tab_to_pbi/transformer.py:_map_relationship()` — apply Signal 1 with captions for logical relationships
- `docs/relationship.md` — update Case 1 from "no inference" to "Signal 1 where available, fallback with warning"
