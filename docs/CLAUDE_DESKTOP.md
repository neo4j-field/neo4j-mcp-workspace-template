# Neo4j MCP Workspace — Claude Desktop Guide

## The key idea: your ontology lives in Neo4j

When you use the workspace through Claude Desktop, the extraction ontology — what entities to extract, what aliases to apply, what values are valid — is stored as a **graph** in your Ontology database.

You can open that database in **Neo4j Bloom** and see it visually:

- `:NodeType` nodes — the entity types Claude will extract (Person, Contract, Organization…)
- `:PropertyDef` nodes — properties on each entity, with their normalizer rules
- `:AliasMap` / `:Alias` nodes — name variants that get canonicalized ("EC" → "European Commission")
- `:Blocklist` / `:BlockedTerm` nodes — values to drop ("researcher", "domain expert"…)
- `:RelationshipType` nodes — relationships between entity types

**You can edit any of this directly in Bloom** — add an alias, remove a blocked term, add a new entity type — then ask Claude to re-extract. Changes are live immediately. No files, no code.

This is the core difference from the Claude Code path, where the schema is a local `.py` file that only a developer can read and edit.

---

## Install the SME skill (recommended)

The workspace ships with an optional **`build-ontology-driven-graph`** skill that walks domain experts through the full flow — domain interview, ontology design, PDF parsing, extraction, refinement in Bloom — without requiring you to know which MCP tool to call when. It is the Claude Desktop equivalent of the `/develop-neo4j-graph` slash command that Claude Code users have.

**Install:**

1. Download `build-ontology-driven-graph.skill` from the [latest skill release](https://github.com/neo4j-field/neo4j-mcp-workspace-template/releases?q=skill-build-ontology) (separate from the DXT release)
2. Drag the `.skill` file into a Claude Desktop conversation
3. Claude Desktop installs it; it is then available in every future conversation

Once installed, just describe your goal in plain language:
> "I have a folder of contracts and I want to build a knowledge graph from them."

Claude will trigger the skill automatically and lead you through the workflow.

> The skill targets Claude Desktop only — it is not loaded by Claude Code or other coding tools (which use `/develop-neo4j-graph` instead).

---

## End-to-end workflow

### 1. Set up the Ontology DB

Ask Claude:
> "Set up the ontology database"

Claude calls `setup_ontology_db` — creates the constraints and indexes needed in your Ontology DB. Do this once per fresh database.

### 2. Design your ontology

Describe your domain to Claude in plain language:
> "I have legal contracts. I want to extract parties, key dates, obligations, and penalty clauses."

Claude will:
- Ask clarifying questions about your domain
- Write the ontology as graph nodes directly to your Ontology DB (`:NodeType`, `:PropertyDef`, `:RelationshipType`, aliases, blocklists)
- Show you the ontology via `generate_schema_from_ontology` so you can review what will be extracted

### 3. Parse your documents

Give Claude the full path to your PDF files:
> "Parse this document: /Users/alice/Documents/contract.pdf"

Claude calls `create_lexical_graph` → `embed_chunks` to build a searchable chunk graph in your Documents DB.

### 4. Extract entities

Ask Claude:
> "Extract entities from the document"

Claude calls `extract_entities(ontology_name=...)` — runs the LLM over every chunk, writes extracted entities and relationships to your Documents DB.

### 5. Explore and refine

- **Query:** ask Claude questions about the documents — it uses vector search, fulltext search, and Cypher to answer
- **Refine in Bloom:** open your Ontology DB in Bloom, edit aliases or blocklists, then ask Claude to re-extract
- **Re-extract:** `extract_entities` with `force=true` re-processes all chunks with the updated ontology

---

## Editing your ontology in Bloom

1. Open **Neo4j Bloom** and connect to your **Ontology DB**
2. Search for your ontology: `MATCH (o:Ontology {name: "my_ontology"}) RETURN o`
3. Expand the graph — you'll see NodeTypes, PropertyDefs, AliasMaps, Blocklists
4. Click any node to edit its properties inline
5. To add a new alias: create an `:Alias {from: "...", to: "..."}` node and connect it to the relevant `:AliasMap`
6. Go back to Claude and ask to regenerate the schema and re-extract

Claude always reads the latest state of the Ontology DB — no restart needed.

---

## How it differs from Claude Code

| | Claude Desktop | Claude Code |
|---|---|---|
| **Ontology storage** | Neo4j graph (Ontology DB) | Local `.py` file |
| **Edit ontology** | Neo4j Bloom — visual, no code | Edit the `.py` file directly |
| **Extraction path** | Always ontology DB (`ontology_name=`) | File-based (`schema=`) or ontology DB |
| **File tools** | None — provide local paths | Full read/write access |
| **Skill invocation** | Natural language | `/develop-neo4j-graph` slash command |
| **GraphRAG tools** | `documents_*` and `ontology_*` prefixed | Single `neo4j-graphrag` instance |
| **Target user** | Domain expert, lawyer, analyst | Developer |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Tools not available after install | `uv` not on PATH | Install `uv`, restart Claude Desktop |
| Connecting to localhost instead of Aura | Old DXT version | Reinstall from latest `.dxt` release |
| Ontology DB tools fail | Wrong Ontology DB credentials | Check URI/username/password in Claude Desktop extension settings |
| `embed_chunks` fails | Missing `OPENAI_API_KEY` | Check OpenAI API Key field in extension settings |
| Re-extraction doesn't reflect ontology edits | Schema not regenerated | Ask Claude to "regenerate the schema" before re-extracting, or use `extract_entities(ontology_name=...)` which always regenerates |
| Entity extraction slow / stuck | Background async processing | Ask Claude to "check extraction status" |
