# Tableau to Power BI: Relationship & Join Resolution

## Background

Tableau represents table relationships in two ways in the `.twb` XML:

1. **Logical relationships** — defined in the `<object-graph>` section. These are Tableau's high-level, cardinality-agnostic relationships. No join type is specified.
2. **Physical joins** — defined in `<relation type="join">` elements. These carry an explicit join type (`left`, `inner`, `full`) and the key columns on each side.

Power BI (TMDL format) represents relationships with a strict directional convention:
- `fromColumn` = the **MANY** side (FK / child / fact table column)
- `toColumn` = the **ONE** side (PK / parent / dimension table column)
- `fromCardinality` must always be `many` unless the relationship is one-to-one (enforced at save time by PBI Desktop)

---

## Case 1: Logical Relationships (object-graph)

**Source**: Tableau `<object-graph>` — no physical join type present.

**Resolution**: Write `fromColumn` and `toColumn` only. Do not write explicit `fromCardinality` or `toCardinality`. PBI Desktop defaults to `many:one`, which is correct for standard dimension-to-fact relationships.

**Why no inference**: Without a join type, there is no structural signal to determine which side is "one". PBI's default is safe and avoids the "From end cardinality must be Many" save error.

**TMDL output example** (`simple_join`):
```tmdl
relationship 'orders_order_id -> returns_order_id'
    fromColumn: orders.order_id
    toColumn: returns.order_id
```

---

## Case 2: Physical Joins

**Source**: Tableau `<relation type="join">` with explicit `join_type`.

**Resolution**: Infer which side is ONE vs MANY using a two-signal algorithm, then write TMDL with `fromColumn` = MANY side (swapping if necessary). No explicit cardinality lines are written when the result is `many:one` (the PBI default).

### Cardinality Inference Algorithm

#### LEFT JOIN — Signal 2 (definitive)

Tableau's join XML is a left-deep tree. In a LEFT JOIN, the LEFT child (the accumulated/preserved table) is definitively the "one" side — it is the anchor whose rows are all retained. The RIGHT child (new table being joined) is the "many" side.

**Result**: LEFT child = one, RIGHT child = many. No override possible.

#### INNER JOIN — Signal 2 extended + Signal 1 confirmation/override

Signal 2 primary: The LEFT expression (accumulated table) is treated as the "one" side by default, consistent with the left-deep tree structure.

Signal 1 confirmation/override: Strip PK suffixes (ID, Key, Code, No), lowercase, singularize both the column base and table name, then exact-match:
- If the RIGHT table's column matches its own table name → RIGHT = one side (Signal 1 overrides Signal 2)
- If the LEFT table's column matches its own table name → LEFT = one side (Signal 1 confirms Signal 2)
- If neither or both match → Signal 2 default stands (LEFT = one)

#### FULL OUTER JOIN — Signal 1 primary + fallback

Signal 2 is unreliable for FULL OUTER (no preserved side). Signal 1 (naming convention) is applied as primary:
- If LEFT column matches LEFT table name → LEFT = one
- If RIGHT column matches RIGHT table name → RIGHT = one
- If ambiguous → fallback: RIGHT child (new/added table) = one (dimension convention)

### Safe cardinality constraint

The algorithm never produces `one:one` or `many:many`. Output is always `one:many` or `many:one`. This prevents PBI data refresh failures (one:one risks duplicate key crash) and broken DAX (many:many disables `RELATED()`).

### TMDL direction fix

After inference, if the inferred ONE side is `from_table` (Tableau's LEFT/anchor), `fromColumn` and `toColumn` are swapped before writing TMDL so that `fromColumn` is always the MANY side. After the swap, PBI defaults apply and no explicit cardinality lines are needed.

**TMDL output example** (`join_custom_rds_pie_map_dual`):
```tmdl
relationship 'Orders_CustomerID -> Customers_CustomerID'
    fromColumn: Orders.CustomerID
    toColumn: Customers.CustomerID

relationship 'OrderItems_OrderID -> Orders_OrderID'
    fromColumn: OrderItems.OrderID
    toColumn: Orders.OrderID

relationship 'OrderItems_ProductID -> Products_ProductID'
    fromColumn: OrderItems.ProductID
    toColumn: Products.ProductID
```

---

## Migration Report

For physical joins, the migration report includes a `relationship_cardinality_warnings` list recording the inferred cardinality and the method used (`signal2_left`, `signal2_inner`, `signal2_confirmed_signal1_inner`, `signal1_override_inner`, `signal1_full`, `fallback`). Users should verify relationships in PBI Desktop Model View after opening.

---

## PBI TMDL Convention Reference

From the official Microsoft TMDL documentation example:
```tmdl
relationship cdb6e6a9-c9d1-42b9-b9e0-484a1bc7e123
    fromColumn: Sales.'Product Key'     -- MANY side (fact table)
    toColumn: Product.'Product Key'     -- ONE side (dimension table)
```

PBI Desktop enforces at save time: *"From end cardinality must always be set to Many, unless the relationship is One-To-One."*
