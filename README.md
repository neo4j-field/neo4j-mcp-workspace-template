# neo4j-mcp-workspace-template

A template for SEs to build Neo4j proof-of-concept graphs from CSVs, PDFs, Markdown, TXT, local HTML and DOCX using MCP servers, with working code to reuse in customer projects. Compatible with **Claude Code**, **Cursor**, **Gemini CLI**, **GitHub Copilot (VS Code)**, **OpenCode**, **OpenAI Codex CLI**, and **Mistral Vibe**.

**Claude Code test prompts:** [Smoke test](SMOKE_TEST_PROMPT.md) · [Follow-up acceptance](FOLLOWUP_ACCEPTANCE_PROMPT.md) · [Benchmark](BENCHMARK_TEST_PROMPT.md). Run smoke first.

## Quick Start

Separate isolated development-snapshot checks on macOS arm64 (uv/Python already
installed) measured **27s for setup** with about **1.26 GiB of dependency cache**,
and **45s for the first two-page Docling parse** with about **505 MiB of model files**.
These are local cache sizes, not measured network transfer; timings vary.
See the [setup measurement](docs/product/reviews/2026-11-24-cold-setup.md) and
[live acceptance](docs/product/reviews/2026-11-24-live-release-acceptance.md) for scope.

```bash
git clone https://github.com/neo4j-field/neo4j-mcp-workspace-template
cd neo4j-mcp-workspace-template
chmod +x setup.sh && ./setup.sh
```

Neo4j prerequisite: `get_neo4j_schema_and_indexes` currently requires compatible **APOC Core** (`apoc.meta.schema`) and permission to execute it. Enable it on the target instance before the full workflow; a default `neo4j-cli docker create` does not enable APOC automatically. PageIndex navigation itself does not require APOC.

Then open your AI coding tool:

| Tool | Command / action | Verify |
|------|-----------------|--------|
| **Claude Code** | `claude` | `/setup-workspace` |
| **Cursor** | Open this folder in Cursor | Ask AI to call `list_example_data_models` |
| **Gemini CLI** | `gemini` | Ask Gemini to call `list_example_data_models` |
| **GitHub Copilot VS Code** | Open folder in VS Code, use Agent mode | Ask Copilot to call `list_example_data_models` |
| **OpenCode** | `opencode` | Ask to call `list_example_data_models` |
| **Codex CLI** | `codex` | Ask Codex to call `list_example_data_models` |
| **Mistral Vibe** | `vibe` (trust the folder when prompted) | Ask Vibe to call `list_example_data_models` |

Setup requires `python3` and `uv`. It creates `.env` with owner-only permissions
(`600`) and treats its contents as data: shell commands, dollar substitutions and
backticks are never evaluated. Quote values containing spaces or `#`; values are
literal, so write complete credentials rather than `${OTHER_VARIABLE}` references.
Existing `.env` contents are preserved; permissions are tightened to `600`.

Before importing data, run `./setup.sh --check-model` to make one small provider
request that verifies structured output using the configured extraction model.
This may incur a small provider charge. Failures stop before config generation,
report recovery steps without printing provider response bodies, and perform no
database writes. Plain `./setup.sh` remains provider-free. The probe checks text
structured output; it does not certify vision, extraction quality or embeddings.

`setup.sh` will:

1. Prompt for your Neo4j credentials and OpenAI API key
2. Write `.env` with your configuration
3. Install dependencies for the local MCP servers, including Docling for PDF parsing (first use may also download model assets)
4. Generate MCP config files for all 7 tools:
   - `.mcp.json` — Claude Code
   - `.cursor/mcp.json` — Cursor
   - `.gemini/settings.json` — Gemini CLI
   - `.vscode/mcp.json` — GitHub Copilot (VS Code)
   - `opencode.json` — OpenCode
   - `.codex/config.toml` — OpenAI Codex CLI
   - `.vibe/config.toml` — Mistral Vibe

Embedding needs `SHOW CONSTRAINT` permission to inspect the reserved uniqueness constraint
`neo4j_mcp_embedding_lock_unique`. If it is absent, a database administrator can precreate
it on `:EmbeddingPublicationLock(indexName)`, or grant `CREATE CONSTRAINT` so the tool can
create it. These checks happen before embedding provider calls. Graph read/write, name
and index privileges are also required; see [embedding permissions](mcp-neo4j-lexical-graph/docs/tools-embedding.md#publication-permissions-and-failures).

---

## Claude Desktop

If you use **Claude Desktop** (not one of the 7 coding tools above), install the workspace as a Desktop Extension — no git clone needed.

### Prerequisites

1. **[uv](https://docs.astral.sh/uv/)** — must be installed before the extension can start (see [Installing uv](#installing-uv) below)

2. **Two Neo4j databases** — the workspace uses a **Documents DB** (chunks, entities) and an **Ontology DB** (extraction schema). Two options:

   | Option | How |
   |--------|-----|
   | **Two Aura instances** | Create two free [AuraDB](https://neo4j.com/cloud/platform/aura-graph-database/) instances — one for documents, one for the ontology. Each has its own URI, username, and password. |
   | **Neo4j Desktop (local)** | Install [Neo4j Desktop](https://neo4j.com/download/), create one DBMS, then add two databases inside it (e.g. `neo4j` and `ontology`). Both share the same URI and credentials. |

   > **Aura free tier note:** each Aura instance has a single database named `neo4j` — you cannot create additional databases. Use two separate instances.

3. **An OpenAI API key** — for embeddings and entity extraction (or configure another provider via Extra Environment Variables in the install dialog)

### Install

1. Download `neo4j-mcp-workspace.dxt` from the [latest release](https://github.com/neo4j-field/neo4j-mcp-workspace-template/releases)
2. Double-click the `.dxt` file — Claude Desktop opens an install dialog
3. Fill in your credentials:
   - **Documents DB** — URI, username, password, database name (e.g. `neo4j`)
   - **Ontology DB** — URI, username, password, database name (e.g. `neo4j` on Aura, `ontology` on Desktop). Leave URI/username/password blank if using the same Neo4j instance as Documents DB.
   - **OpenAI API key** — for embeddings; also used for extraction if your extraction model is OpenAI
   - **Extraction model** — defaults to `openai/gpt-6-luna`; change to any [LiteLLM-compatible](https://docs.litellm.ai/docs/providers) model
4. Click **Install** — all MCP servers start automatically

### What makes it different

The workspace stores your extraction ontology as a **graph in your Ontology DB**. Open it in **Neo4j Bloom** to visualize and edit it directly — add aliases, adjust blocklists, define new entity types — then ask Claude to re-extract. Changes are live immediately. No files, no code.

A companion **SME skill** (`build-ontology-driven-graph`) walks non-developers through the full flow — install it via drag-drop from the [latest skill release](https://github.com/neo4j-field/neo4j-mcp-workspace-template/releases?q=skill-build-ontology). See [Install the SME skill](docs/CLAUDE_DESKTOP.md#install-the-sme-skill-recommended) in the Claude Desktop Guide.

→ See the [Claude Desktop Guide](docs/CLAUDE_DESKTOP.md) for the full workflow, Bloom editing, and troubleshooting.

### Providing files to the workspace

The MCP servers run on your local machine and access your local filesystem. When Claude asks you for a PDF or CSV file, provide the **full path on your computer** (e.g. `/Users/alice/Documents/report.pdf` on Mac, `C:\Users\alice\Documents\report.pdf` on Windows).

> Do not use the Claude Desktop file upload button — uploaded files go to a sandbox the MCP servers cannot reach. Save the file to your disk and give Claude the path instead.

---

## Requirements

- **[uv](https://docs.astral.sh/uv/)** — required to run all MCP servers (provides `uvx`)
- **Neo4j with vector-index support** — compatibility checks cover 5.26.33 and 2025.12.1; native vector values and filtered indexes are used when supported
  - [Neo4j Desktop](https://neo4j.com/download/) or [AuraDB](https://neo4j.com/cloud/platform/aura-graph-database/)
- **LLM provider** — for embedding generation and entity extraction (see [LLM Configuration](#llm-configuration) below)
- **Google MCP Toolbox** (optional) — only if using BigQuery as a data source

### Installing uv

`uv` is a fast Python package manager that also provides `uvx` — used to run the MCP servers without a manual Python setup. Install it once on your machine:

**macOS / Linux**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Then restart your terminal (or run `source $HOME/.local/bin/env`).

**Windows (PowerShell)**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
Then restart your terminal.

**Verify the install**
```bash
uv --version   # should print e.g. uv 0.6.x
uvx --version  # same binary, should also work
```

> **Note for Claude Desktop users:** `uv` must be installed and on your PATH before the Neo4j workspace extension can start. Claude Desktop does not bundle `uv`.

Full docs: [docs.astral.sh/uv/getting-started/installation](https://docs.astral.sh/uv/getting-started/installation/)

---

## MCP Servers

This workspace configures five MCP servers:

### Data Modeling

Designs and validates graph schemas from sample data. Provides example data models and Mermaid visualizations.

- **Server:** `mcp-neo4j-data-modeling` (remote via `uvx`)
- **Required credentials:** none

### Ingest

Loads structured CSV data into Neo4j using parameterized Cypher queries generated by the Data Modeling server.

- **Server:** `mcp-neo4j-ingest` (local — `mcp-neo4j-ingest/`)
- **Required credentials:** Neo4j connection vars

### Lexical Graph

Parses PDFs, Markdown, TXT, local HTML/XHTML and DOCX into a searchable graph with `Document`, `Chunk`, and optional `Image`/`Table`/`Section`/`Page` nodes, embeddings, and fulltext indexes.

| Choose | When to use it |
|--------|----------------|
| Automatic `document` routing | Markdown, TXT, local HTML/XHTML and DOCX; native text/heading parsing without PDF rendering |
| `pymupdf` (default for PDFs) | Text-heavy PDFs; fast extraction without layout-model downloads |
| `docling` | Section hierarchy, structured tables, and mixed layouts |
| `page_image` | Slides, diagrams, and pages whose visual arrangement carries meaning; requires a vision model |

See the [parse-mode guide](.agents/skills/develop-neo4j-graph/references/HANDLE_UNSTRUCTURED_DATA.md#parse-mode-guide) for the full workflow.

Place the new file types in `data/documents/` and pass the absolute file/folder
path to `create_lexical_graph`; supported extensions are selected automatically.
Then call `chunk_lexical_graph` (`structured` for heading-aware documents),
`embed_chunks` and the existing extraction workflow. Mixed PDF/document folders
are supported. Native headings power PageIndex; TXT stays literal and flat.

Pageless sources use source-file/element or line anchors rather than page numbers.
DOCX embedded images and tables are retained; referenced HTML/Markdown images stay
as references, with no browser execution or asset fetching. Text files must be UTF-8.
See the [document workflow](.agents/skills/develop-neo4j-graph/references/DOCUMENT_MODE.md).

- **Server:** `mcp-neo4j-lexical-graph` (local — `mcp-neo4j-lexical-graph/`)
- **Required credentials:** Neo4j connection vars + LLM API key + `EMBEDDING_MODEL`

### Entity Graph

Extracts structured entities from lexical graph chunks using an LLM. Supports 100+ providers via LiteLLM. Processing runs asynchronously in the background.

- **Server:** `mcp-neo4j-entity-graph` (local — `mcp-neo4j-entity-graph/`)
- **Required credentials:** Neo4j connection vars + LLM API key + `EXTRACTION_MODEL`

### GraphRAG

Read/write Cypher queries, vector search, fulltext search, and graph-traversal queries. Replaces the standalone Cypher server and adds RAG retrieval on top.

- **Server:** `mcp-neo4j-graphrag` (local — cloned by `setup.sh` at the commit in `mcp-neo4j-proxy/src/mcp_neo4j_proxy/graphrag_revision.txt`)
- **Source review:** [GraphRAG draft PR #2](https://github.com/neo4j-field/mcp-neo4j-graphrag/pull/2). The proxy source uses the same Git pin; source installs require Git. Published Desktop artifact alignment remains part of release verification.
- **Key tools:** `read_neo4j_cypher`, `write_neo4j_cypher`, `get_neo4j_schema_and_indexes`, `vector_search`, `fulltext_search`, `search_cypher_query`, `read_node_image`, `get_ontology`, `list_retrieval_documents`, `get_document_outline`, `get_section_content`, `get_document_content`
- **Required credentials:** reads from `.env` via python-dotenv

Document navigation tools appear only when the connected database contains usable
active lexical content; section tools additionally require section structure.
Refresh tool discovery after ingestion if the client caches its tool list.

For document-tree retrieval, discover a document, read its outline, choose section
IDs and read the source content. Continue using the returned pagination cursors.
Section-aware parses carry heading paths and page ranges; flat documents remain
readable through `get_document_content`. No embeddings or hierarchy LLM calls are
needed for navigation.

For text-to-Cypher, call `get_ontology` for domain meaning and vocabulary before
writing a query. Configure `ONTOLOGY_FILE` for a spec artifact, or use the template
Ontology DB (`ONTOLOGY_NAME`, `NEO4J_ONTOLOGY_DATABASE`). Keep schema/index discovery
for physical details and read queries for actual data values. Full spec retrieval
support is broader than the extraction adapter's subset.

### BigQuery (optional)

Connects to BigQuery as a source database. Requires the [Google MCP Toolbox](https://github.com/googleapis/genai-toolbox) CLI.

```bash
brew install mcp-toolbox
```

---

## Workflow

### Structured data (CSV)

1. **Discovery** — analyze CSV samples; identify entities, relationships, and use cases
2. **Model** — design a graph data model with the Data Modeling server
3. **Ingest** — load CSV data into Neo4j with the Ingest server
4. **Query** — generate Cypher for each use case
5. **Validate** — run queries and verify results address the use cases

### Documents (PDF, Markdown, TXT, HTML, DOCX) — use `/develop-neo4j-graph`

1. **Discovery** — review source documents; non-PDF formats route automatically, PDFs retain their parser choice
2. **Use case** — infer CHATBOT or ANALYTICAL mode from use case description
3. **Model** — design a graph data model with the Data Modeling server
4. **Lexical Graph** — parse documents, chunk (if needed), generate descriptions (if images/tables), embed
5. **Schema + validators** — export extraction schema and review Pydantic validators
6. **Entity Graph** — extract structured entities from chunks
7. **Q&A / Analysis** — answer questions (CHATBOT) or generate Cypher reports (ANALYTICAL)
8. **Report** — save results to `outputs/reports/`

Use the `develop-neo4j-graph` skill for the full guided workflow (CSV + PDF, CHATBOT or ANALYTICAL mode):

| Tool | How to invoke |
|------|--------------|
| Claude Code | `/develop-neo4j-graph` |
| Gemini CLI | `/develop-neo4j-graph` (TOML slash command) or describe the task (auto-triggered) |
| Codex CLI | `$develop-neo4j-graph` or describe the task (auto-triggered) |
| Cursor, GitHub Copilot VS Code | Describe the task — skill auto-triggers |
| OpenCode | Select `develop-neo4j-graph` from the agent picker |
| Mistral Vibe | Describe the task — skill auto-triggers (discovered from `.agents/skills/`) |

## Rebuild this POC / start fresh

For a shared database, select the exact source chunks/pages and keep a stable extraction
scope. Re-running with changed source content, schema, or configuration refreshes those
sources; `force=True` also refreshes unchanged ones:

```python
extract_entities(
    schema="/absolute/path/to/outputs/schemas/poc.py",
    source_ids=["your-exact-chunk-id"],
    extraction_scope="my-poc",
    force=True,
)
```

This replaces tracked contributions for the selected sources in that scope. Other
scopes and existing CSV/user properties are preserved by the default
`property_policy="preserve_existing"`; proposals and conflicts remain inspectable.
An extraction failure preserves the previous domain output. Inspect legacy sources
before rebuilding: old untracked provenance requires fresh explicitly selected sources
or a reviewed migration. This operation does not reset CSV imports or delete documents.

For a completely fresh run, use a new disposable database and point setup at it, then
restart your coding tool and run the CSV + PDF workflow again. Keep the old database
until the new report passes validation. A namespace or document name alone does not
isolate domain nodes: matching labels and merge keys can still share nodes.

The [release checklist](docs/product/RELEASE_CHECKLIST.md) tracks the remaining checks
before publishing this work.

---

## LLM Configuration

Both `EMBEDDING_MODEL` and `EXTRACTION_MODEL` accept any [LiteLLM-compatible](https://docs.litellm.ai/docs/providers) model string. The defaults use OpenAI, but you can swap to any provider — including local models via Ollama — by editing two lines in `.env`.

### Default (OpenAI)

```env
EMBEDDING_MODEL=text-embedding-3-small
EXTRACTION_MODEL=gpt-6-luna
```

Fast, high quality, requires an OpenAI API key.

### Local models via Ollama

Run models entirely on your own hardware — no API key needed. Install [Ollama](https://ollama.com), pull the models, then update `.env`:

```env
EMBEDDING_MODEL=ollama/nomic-embed-text
EXTRACTION_MODEL=ollama/qwen3:8b
```

```bash
ollama pull nomic-embed-text
ollama pull qwen3:8b
```

**Recommended local models:**


| Use case                  | Model              | Size   | Notes                                            |
| ------------------------- | ------------------ | ------ | ------------------------------------------------ |
| Embeddings                | `nomic-embed-text` | 274 MB | 768-dim, good retrieval quality                  |
| Text extraction           | `qwen3:8b`         | 5.2 GB | Best quality/speed balance for entity extraction |
| Text extraction (lighter) | `phi4-mini`        | 2.5 GB | Faster, lower relationship recall (~75% vs 100%) |
| Vision extraction         | `qwen3.5:9b`       | 6.6 GB | For `page_image` parse mode on slides/diagrams   |


**Tradeoffs vs cloud models:** Local extraction is slower due to sequential processing (expect 15–45 min per 100 chunks vs ~2 min with `gpt-5.4-mini`). Quality-wise, `qwen3:8b` matches cloud models for simple entity extraction, but `phi4-mini` misses relationships.

### Other providers

`setup.sh` only prompts for `OPENAI_API_KEY`. For other providers, run `setup.sh` first, then add the provider's credentials to `.env` manually:

```env
# Mistral
MISTRAL_API_KEY=...
EMBEDDING_MODEL=mistral/mistral-embed
EXTRACTION_MODEL=mistral/mistral-small-latest

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
EXTRACTION_MODEL=anthropic/claude-haiku-4-5-20251001

# Azure OpenAI
AZURE_API_KEY=...
AZURE_API_BASE=https://YOUR_RESOURCE.openai.azure.com
AZURE_API_VERSION=2024-02-01
EXTRACTION_MODEL=azure/gpt-4o-mini

# AWS Bedrock
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION_NAME=us-east-1
EXTRACTION_MODEL=bedrock/anthropic.claude-3-haiku-20240307-v1:0

# Google Gemini
GEMINI_API_KEY=...
EXTRACTION_MODEL=gemini/gemini-2.0-flash

# Ollama (local, no key needed — see section above)
EXTRACTION_MODEL=ollama/qwen3:8b
```

Full provider list: [docs.litellm.ai/docs/providers](https://docs.litellm.ai/docs/providers)

---

## Setup

### Primary: `./setup.sh`

```bash
chmod +x setup.sh && ./setup.sh
```

The script is idempotent. Re-run it any time to:

- Regenerate all 7 MCP config files after credential changes
- Re-install server dependencies after a `git pull`

Docling is part of the standard lexical-graph environment; setup no longer asks
whether to install it. Its PDF/ML dependencies can require substantial downloads,
and first use may fetch additional model assets. Download size and duration vary
by platform, network and cache; no fixed installation-time estimate is assumed.
Setup prints each server's dependency-sync duration and a final timing summary.
The `.venv present/absent` labels describe the directory before sync, not proof of
a warm/cold package cache. Whole-second `0s` results mean less than one second.
Older `INSTALL_DOCLING=false` entries are ignored without rewriting `.env`.

### Alternative: Manual Setup

Manual setup steps

**1. Create `.env`**

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
# Edit .env with your Neo4j credentials and API keys
```

**2. Clone the graphrag server**

```bash
git clone --depth 1 https://github.com/neo4j-field/mcp-neo4j-graphrag
```

**3. Install local server dependencies**

```bash
uv sync --directory mcp-neo4j-ingest
uv sync --directory mcp-neo4j-lexical-graph --extra docling
uv sync --directory mcp-neo4j-entity-graph
uv sync --directory mcp-neo4j-graphrag
```

**4. Generate MCP config files**

Use `.cursor/mcp.json.example` as a reference — replace `/absolute/path/to/` with your actual workspace path, then adapt the format for each tool:

```bash
# Cursor — mcpServers key
cp .cursor/mcp.json.example .cursor/mcp.json
# Edit: replace /absolute/path/to/ with actual path

# Claude Code — identical format, different filename
cp .cursor/mcp.json .mcp.json

# Gemini CLI — identical format, different filename
mkdir -p .gemini && cp .cursor/mcp.json .gemini/settings.json

# GitHub Copilot VS Code — rename root key from "mcpServers" to "servers"
# Edit .vscode/mcp.json with the server entries under "servers": { ... }

# OpenCode — root key "mcp", command is an array, type "local"
# See opencode.json generated by setup.sh for format reference

# Codex CLI — TOML format
# See .codex/config.toml generated by setup.sh for format reference

# Mistral Vibe — TOML format, array-of-tables `[[mcp_servers]]` with name/transport/command/args
# See .vibe/config.toml generated by setup.sh for format reference
```

All local servers read credentials from `.env` via python-dotenv — no credentials in config files.



---

## Supported Tools

| Tool | MCP config | Skill/workflow system | Context file |
|------|-----------|----------------------|--------------|
| Claude Code | `.mcp.json` | `/develop-neo4j-graph` slash command (`.claude/skills/`) | `CLAUDE.md` |
| Cursor | `.cursor/mcp.json` | auto-triggered (`.agents/skills/`) | — |
| Gemini CLI | `.gemini/settings.json` | auto-triggered + `/develop-neo4j-graph` command | `GEMINI.md` |
| GitHub Copilot VS Code | `.vscode/mcp.json` | auto-triggered (`.agents/skills/`) | `.github/copilot-instructions.md` |
| OpenCode | `opencode.json` | agent picker (`.opencode/agents/`) | — |
| Codex CLI | `.codex/config.toml` | `$develop-neo4j-graph` or auto-triggered | `AGENTS.md` |
| Mistral Vibe | `.vibe/config.toml` | auto-triggered (`.agents/skills/`) | `AGENTS.md` |

All generated config files contain absolute paths and are gitignored — run `./setup.sh` on each machine. `AGENTS.md` is a shared convention read by both Codex CLI and Mistral Vibe — its instructions are written to be tool-agnostic rather than assuming either one specifically.

The skill workflow is defined once in `.agents/skills/develop-neo4j-graph/SKILL.md` (the [Agent Skills](https://agentskills.io) open standard) and referenced by all tools.

---

## Project Structure

```
neo4j-mcp-workspace-template/
├── setup.sh                        # One-time setup script
├── .env.example                    # Documents all environment variables
├── CLAUDE.md                       # Claude Code agent context
├── GEMINI.md                       # Gemini CLI agent context
├── AGENTS.md                       # Codex CLI + Mistral Vibe agent context (shared convention)
├── .agents/
│   └── skills/
│       └── develop-neo4j-graph/    # Cross-tool skill (Agent Skills standard)
│           ├── SKILL.md            # Workflow definition
│           └── references/         # Detailed reference docs per mode
├── .gemini/
│   └── commands/
│       └── develop-neo4j-graph.toml  # Gemini CLI slash command
├── .opencode/
│   └── agents/
│       └── develop-neo4j-graph.md  # OpenCode agent
├── .github/
│   └── copilot-instructions.md     # GitHub Copilot VS Code context
├── data/                           # Input data (gitignored contents, tracked structure)
│   ├── csv/                        # Structured data
│   └── pdf/                        # PDF documents
├── outputs/                        # Generated outputs (gitignored contents, tracked structure)
│   ├── data_models/                # Graph data model JSON files
│   ├── queries/                    # Cypher query YAML files
│   ├── reports/                    # Markdown reports
│   └── schemas/                    # Pydantic extraction schema files
├── demo/                           # Demo data scripts and reference outputs (committed)
│   └── expected/                   # Reference outputs for comparison
├── mcp-neo4j-ingest/               # Local ingest MCP server
├── mcp-neo4j-lexical-graph/        # Local lexical graph MCP server
├── mcp-neo4j-entity-graph/         # Local entity graph MCP server
├── mcp-neo4j-graphrag/             # Cloned by setup.sh (gitignored)
├── .mcp.json                       # Generated (gitignored) — Claude Code MCP config
├── .codex/
│   └── config.toml                 # Generated (gitignored) — Codex CLI MCP config
├── .vibe/
│   └── config.toml                 # Generated (gitignored) — Mistral Vibe MCP config
├── .cursor/
│   ├── mcp.json                    # Generated (gitignored) — Cursor MCP config
│   └── mcp.json.example            # Template for manual setup
├── .gemini/
│   └── settings.json               # Generated (gitignored) — Gemini CLI MCP config
├── .vscode/
│   └── mcp.json                    # Generated (gitignored) — GitHub Copilot MCP config
├── opencode.json                   # Generated (gitignored) — OpenCode MCP config
└── .claude/
    └── skills/
        ├── develop-neo4j-graph/    # Symlink → .agents/skills/develop-neo4j-graph/
        ├── setup-workspace/        # /setup-workspace validation skill
        └── dev/evaluate-pipeline/  # /dev:evaluate-pipeline skill
```

### Synthetic acceptance dataset

Generate reusable all-format smoke and benchmark fixtures with `scripts/generate-synthetic-dataset.sh --profile smoke` (or `benchmark`). The benchmark contains 10,000 product rows plus 102 auxiliary CSV rows and a 50-page PDF. See the [SE walkthrough, expected answers and validation commands](docs/product/SYNTHETIC_DATASET.md).
