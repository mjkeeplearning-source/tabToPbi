# Power BI Modeling MCP — Deep Dive for Tableau → PBI Migration

*Researched: 2026-04-17*

## What It Is

A **precompiled .NET binary** distributed via npm (`@microsoft/powerbi-modeling-mcp`). No source code in the GitHub repo — just docs and binaries. It implements the MCP stdio transport: launched as a subprocess by an LLM client (VS Code Copilot, Claude Desktop, Cursor, etc.), bridging the LLM to the **Tabular Object Model (TOM)** — Microsoft's Analysis Services API.

Current version: **0.5.0-beta.3** (Public Preview, tools may change before GA).

GitHub: https://github.com/microsoft/powerbi-modeling-mcp

---

## Three Connection Modes

| Mode | Backend | Prerequisite |
|------|---------|-------------|
| **A — PBI Desktop** | Live AS instance inside running PBI Desktop | PBI Desktop open with the file |
| **B — Fabric workspace** | Cloud XMLA endpoint | Premium/Fabric capacity + Azure credentials |
| **C — PBIP files on disk** | Reads/writes TMDL files directly, no PBI Desktop | Node.js 18+, TMDL format |

**Mode C is the most relevant for automated pipelines** — zero cloud dependencies, zero running apps.

---

## What It Can Do (21 Tool Categories)

High-value tools for migration:

| Tool | Capability |
|------|-----------|
| `table_operations` | Create/update/delete tables |
| `column_operations` | CRUD columns, datatypes, formatting |
| `measure_operations` | CRUD DAX measures, move between tables |
| `relationship_operations` | Create/update/delete/activate relationships |
| `partition_operations` | Create/update Power Query M partitions (data sources) |
| `dax_query_operations` | Execute and validate DAX against real data |
| `transaction_operations` | Begin/commit/rollback for atomic batches |
| `named_expression_operations` | Power Query parameters |

---

## The Hard Limit — No Report Layer

> "The Power BI Modeling MCP server can only execute modeling operations. It **cannot modify other types of Power BI metadata, such as report pages**."

This is a permanent architectural boundary. TOM has no concept of report visuals. The MCP server is **semantic model only** — it cannot touch `page.json`, `visual.json`, `pages.json`, or anything in the `.Report/` folder. Our `generator.py` must continue to own that entirely.

---

## Python Integration (Conceptual)

The server speaks JSON-RPC over stdio. Python can drive it via:
- The official `mcp` Python SDK (`pip install mcp`)
- Direct subprocess + JSON-RPC

```python
# Conceptual — drive MCP from Python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
    command="npx",
    args=["-y", "@microsoft/powerbi-modeling-mcp@latest", "--start", "--skipconfirmation"]
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        # Connect to PBIP folder on disk
        await session.call_tool("database_operations", {
            "operation": "importFromTmdlFolder",
            "path": "C:/output/MyReport.SemanticModel/definition"
        })
        # Create a DAX measure
        await session.call_tool("measure_operations", {
            "operation": "create",
            "tableName": "Orders",
            "measureName": "Total Sales",
            "expression": "SUM(Orders[Sales])"
        })
```

---

## Active Blocker — Issue #89

Version 0.4.0+ prints an ASCII banner and calls `Console.ReadKey()` on startup, which **crashes when stdin is redirected** (i.e., exactly the headless subprocess scenario). This currently breaks any Python subprocess integration. **Unfixed as of 2026-04-17.**

---

## Limitations Relevant to Our MVP

| Limitation | Impact |
|-----------|--------|
| No report page/visual manipulation | Our `.Report/` folder is entirely outside MCP scope |
| Console.ReadKey bug (#89) | Headless Python automation currently broken |
| TMDL required for Mode C | We output `model.bim` (TMSL) as fallback; TMDL also requires preview feature in PBI Desktop |
| Designed for LLM agents, not deterministic scripts | For exact, structured migration data, file writing is more reliable |
| Public Preview — tools may change | Not stable enough for production automation yet |

---

## Where MCP Adds Value vs. File-Based Approach

### Keep File-Based (Now and Always for Some Areas)

| Area | Why |
|------|-----|
| Entire `.Report/` folder | MCP cannot touch it — permanent limitation |
| `page.json`, `visual.json`, `pages.json` | Completely outside MCP scope |
| `model.bim` / TMDL generation from parsed dict | Deterministic, fast, no subprocess overhead |
| Headless CI/CD | MCP Mode C blocked by bug #89 |

### Where MCP Could Add Value (Future)

| Use Case | When |
|----------|------|
| **Post-generation DAX validation** | Run translated measures against real data in PBI Desktop (Mode A) — requires PBI Desktop open, not headless |
| **Interactive model refinement** | User opens VS Code after migration, uses Copilot Chat to rename/refactor the generated model |
| **Bulk measure refactoring** | Post-migration: restructure into calculation groups, add descriptions, enforce naming conventions |
| **RLS role creation** | If Tableau RLS patterns ever come into scope |

### Future Pipeline Shape (After Bug Fix + TMDL Switch)

```
parser.py → transformer.py → generator.py (writes TMDL files)
    → [optional] mcp_validator.py  <- validates DAX against real data
    -> output/ + migration_report.json
```

---

## Bottom Line

**Do not integrate MCP into the pipeline now.** The MCP server is not a replacement for `generator.py` — it covers the semantic model layer only and is currently broken for headless use. Its real value to this project is as a **post-generation interactive validation and refinement tool** a user runs in VS Code after the migration script completes.

Watch for the Console.ReadKey bug fix (issue #89) and revisit once DAX validation becomes a priority.
