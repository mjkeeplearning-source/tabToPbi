# NeedTofix — Deferred Fixes

## Text Encoding Parsing (Tableau `<encodings><text>`)

### What we tried to fix
Sheet 4 of `simple_join_sorted_test.twb` is a text table (crosstab) with:
- Rows: `category` (dimension)
- Text card: `SUM(profit)` (measure)

In Tableau, text table measures live in `<panes><pane><encodings><text column="[ds].[sum:profit:qk]" />` — NOT in the `<rows>` or `<cols>` shelf. The parser only read `<rows>` and `<cols>`, so `SUM(profit)` was invisible: the PBI table visual showed only `category` with no measure column.

### Change made
In `tab_to_pbi/parser.py`, inside `_parse_sheets()`, added logic after parsing `cols_text` to also read `./table/panes/pane/encodings/text` elements and append them to `col_fields`:

```python
col_fields = _parse_shelf_fields(cols_text)
for text_enc in ws.findall("./table/panes/pane/encodings/text"):
    col_attr = text_enc.get("column", "")
    if col_attr:
        col_fields.extend(_parse_shelf_fields(col_attr))
```

New test file added: `tests/test_text_encoding.py` (3 tests, all passing).

### What it broke
- **Sheet 1 bar chart**: Tableau bar chart changed to a PBI Column chart (visual type regression).
- **Sheet 4 table**: PBI tabular visual changed to a bar chart instead of a table (mark type inference regression).

### Root cause hypothesis
The `<encodings><text>` element is present on ALL Tableau sheets, not just text tables. On a bar chart, `<text>` encodes the data label value (e.g. what is shown on the mark). Appending that field into `col_fields` on every visual type confuses the transformer's visual type inference logic and shelf layout, causing it to pick the wrong PBI visual type.

### Fix needed
Before appending text encoding fields to `col_fields`, gate on the sheet being a text table. A text table in Tableau is characterised by:
- `mark_type == "Automatic"` AND
- `rows` is non-empty AND
- `cols` is empty (i.e. `cols_text.strip() == ""`)

Only apply the `<encodings><text>` → `col_fields` logic when those three conditions are true. For all other visual types, the text encoding is a data label, not a measure column.
