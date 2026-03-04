---
name: setup-workspace
description: Verify that the neo4j-mcp-workspace-template is correctly configured. Checks .env, .cursor/mcp.json, MCP server availability, and Neo4j connectivity. Use when you want to confirm setup is working or diagnose connection issues.
---

# Setup Workspace — Validation Skill

Verify that the neo4j-mcp-workspace-template is correctly configured and all MCP servers are reachable.

## Steps

### 1. Check configuration files

Report whether the following files exist:
- `.env` — credential file created by `setup.sh`
- `.cursor/mcp.json` — Cursor MCP configuration
- `.mcp.json` — Claude Code MCP configuration (project root)

If any are missing, stop and tell the user:
> "Run `./setup.sh` first, then reopen this folder in Cursor."

### 2. Report environment variables

Read `.env` and report which keys are **set** (non-empty) vs **missing**. Do **not** print the values of any credentials.

Expected keys:
- `NEO4J_URI` ✓/✗
- `NEO4J_USERNAME` ✓/✗
- `NEO4J_PASSWORD` ✓/✗
- `NEO4J_DATABASE` ✓/✗
- `OPENAI_API_KEY` ✓/✗ (needed for lexical-graph + entity-graph)
- `EMBEDDING_MODEL` ✓/✗
- `EXTRACTION_MODEL` ✓/✗
- `BIGQUERY_PROJECT` ✓/✗ (optional)

### 3. Check MCP tool availability

For each of the 5 servers, confirm whether its tools are available:

| Server | Status |
|--------|--------|
| `neo4j-data-modeling` | available / not loaded |
| `neo4j-ingest` | available / not loaded |
| `neo4j-lexical-graph` | available / not loaded |
| `neo4j-entity-graph` | available / not loaded |
| `neo4j-graphrag` | available / not loaded |

If tools are not loaded despite `mcp.json` existing: tell the user to reopen the folder in Cursor.

### 4. Test Neo4j connectivity

If `neo4j-graphrag` is available, run:
```cypher
RETURN 'ok' AS status
```

Report:
- **Connected** — Neo4j is reachable and credentials are valid
- **Connection failed** — show the error message; tell user to check `NEO4J_URI` and credentials in `.env`, then re-run `./setup.sh`

### 5. Summarize readiness

Print a readiness table:

```
╔════════════════════════════════════════════════╗
║           Workspace Readiness Report           ║
╠════════════════════════════════════════════════╣
║  Configuration files    OK / MISSING           ║
║  Neo4j connection       OK / FAILED            ║
║  neo4j-data-modeling    online / not loaded    ║
║  neo4j-ingest           online / not loaded    ║
║  neo4j-lexical-graph    online / not loaded    ║
║  neo4j-entity-graph     online / not loaded    ║
║  neo4j-graphrag         online / not loaded    ║
║  Embeddings capable     yes (openai) / no      ║
║  Entity extraction      yes (openai) / no      ║
║  BigQuery               configured / not set   ║
╚════════════════════════════════════════════════╝
```

### 6. If anything is missing

Give exact commands to fix each issue:

| Issue | Fix |
|-------|-----|
| `.env` missing | `./setup.sh` |
| `.cursor/mcp.json` missing | `./setup.sh` |
| MCP servers not loaded | Reopen folder in Cursor (MCP loads on IDE start) |
| Neo4j unreachable | Check Neo4j is running; re-run `./setup.sh` to update credentials |
| No LLM API key | Add `OPENAI_API_KEY` to `.env`, re-run `./setup.sh` |
