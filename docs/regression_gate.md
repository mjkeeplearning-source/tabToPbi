# Regression Gate

Prevents code changes from breaking already-working Tableau → Power BI conversions.

When a workbook is registered, the pipeline output is snapshotted. On every commit and push, the pipeline re-runs against all registered workbooks and the new output is compared to the saved snapshot. Any difference blocks the commit.

---

## How It Works

### Registration (one-time per workbook)

```
uv run python tests/regression/register.py input/simple.twb
```

This runs the deterministic pipeline (parse → transform → generate → dashboard pages) **without calling Claude** for formula translation, then saves the output as a baseline snapshot.

Snapshot files captured per workbook:
- All `.tmdl` files (semantic model tables, relationships, database, model)
- `visual.json`, `page.json`, `pages.json`, `report.json`
- `definition.pbir`, `definition.pbism`

Debug files (`parsed.json`, `transformed.json`, `migration_report.json`) are excluded.

Snapshots are stored in `tests/snapshots/<stem>/` and committed to git so the baseline travels with the code.

### Check (automatic on commit/push)

The pre-commit and pre-push hooks run:

```
uv run pytest tests/test_regression.py -x -q --tb=short
```

For each registered workbook:
1. Re-runs the same no-Claude pipeline into a temp directory
2. Collects the same set of output files
3. Compares each file against the saved snapshot (byte-for-byte)
4. On any difference: prints a unified diff and blocks the commit

Fails fast — stops at the first workbook that differs.

### Updating a Snapshot (after intentional changes)

When you make a code change that intentionally alters the pipeline output (e.g. a new field in `visual.json`, a TMDL format fix), re-register the affected workbook to accept the new output as the baseline:

```
uv run python tests/regression/register.py input/simple.twb
```

Commit the updated snapshot files alongside your code change.

---

## Adding a Workbook to the Regression Gate

### Prerequisites
- The workbook must be in `input/` and must pass end-to-end through the pipeline with 0 validator errors
- Manually verify the generated Power BI report opens correctly in PBI Desktop

### Steps

**1. Run the pipeline manually and verify it opens in PBI Desktop**

```
uv run tab_to_pbi/main.py input/YourWorkbook.twb
```

Open `output/YourWorkbook.Report/` in PBI Desktop. Confirm visuals render correctly, no error dialogs.

**2. Register the workbook**

```
uv run python tests/regression/register.py input/YourWorkbook.twb
```

Output confirms the files snapshotted and updates `tests/regression/registry.yaml`:

```
Snapshotting 14 files for 'YourWorkbook'
  YourWorkbook.Report\definition.pbir
  YourWorkbook.Report\definition\report.json
  ...
Registered 'YourWorkbook': 4 visuals, 2 calc fields
Registry: tests\regression\registry.yaml
```

**3. Verify the gate passes**

```
uv run pytest tests/test_regression.py -v
```

All registered workbooks should show `PASSED`.

**4. Commit both the snapshot and registry**

```
git add tests/snapshots/YourWorkbook tests/regression/registry.yaml
git commit -m "Register YourWorkbook in regression gate"
```

---

## Registry File

`tests/regression/registry.yaml` lists all registered workbooks. Edited automatically by `register.py` — do not edit manually.

```yaml
workbooks:
- stem: simple
  path: input/simple.twb
  data_dir: data
  expected_visual_count: 3
  expected_calc_field_count: 0
  snapshot_path: tests/snapshots/simple
- stem: simple_join
  path: input/simple_join.twb
  data_dir: data
  expected_visual_count: 2
  expected_calc_field_count: 2
  snapshot_path: tests/snapshots/simple_join
```

Fields:

| Field | Description |
|-------|-------------|
| `stem` | Workbook filename without extension |
| `path` | Path to the `.twb` or `.twbx` file |
| `data_dir` | Folder containing data files (`.xlsx`, `.csv`); `data` for most workbooks |
| `expected_visual_count` | Number of `visual.json` files in the snapshot |
| `expected_calc_field_count` | Number of calculated fields found in the workbook |
| `snapshot_path` | Path to the snapshot directory |

---

## Removing a Workbook from the Regression Gate

```
uv run python tests/regression/deregister.py simple
# or pass the twb path — the stem is extracted automatically
uv run python tests/regression/deregister.py input/simple.twb
```

This deletes the snapshot directory and removes the entry from `registry.yaml`. Commit the registry change and the snapshot deletion together.

---

## File Layout

```
tests/
  regression/
    registry.yaml          ← workbook registry (auto-managed by register.py)
    register.py            ← CLI to register a workbook as a baseline
  snapshots/
    simple/
      simple.Report/
        definition.pbir
        definition/
          report.json
          pages/
            pages.json
            ReportSection1/
              page.json
              visuals/
                visual_1/visual.json
      simple.SemanticModel/
        definition.pbism
        definition/
          database.tmdl
          model.tmdl
          relationships.tmdl
          tables/
            Orders.tmdl
  test_regression.py       ← parametrized pytest tests (one per registered workbook)
```

---

## Troubleshooting

**"Snapshot not found — re-run register.py"**
The snapshot directory is missing. Run `register.py` for that workbook and commit the result.

**"Files missing from new output"**
The pipeline no longer produces a file that was in the snapshot. A code change removed something. Either fix the regression or re-register if the removal is intentional.

**"Unexpected new files not in snapshot"**
The pipeline now produces extra files. Re-register if the new files are expected.

**Gate passes but PBI Desktop shows errors**
The regression gate only checks deterministic output (no Claude). Translated DAX measures are not included. Verify Claude translation separately by running the full pipeline with `main.py`.

**Hook not running**
Git hooks in `.git/hooks/` are local-only and not committed. If you cloned fresh or another developer doesn't have the hooks, they need to be set up manually. Copy `.git/hooks/pre-commit` and `.git/hooks/pre-push` from a working machine or document the setup step in onboarding.
