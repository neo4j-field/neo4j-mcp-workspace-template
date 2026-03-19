---
name: evaluate-pipeline
description: > **Internal use only.** Run this after completing a `/build-pdf-chatbot` or `/develop-neo4j-graph` run to evaluate how well the skill and MCP tools performed. Produces a structured report to guide improvement of skills and server tools.
---

# Evaluate Pipeline — Template Development Tool

---

## What this evaluates

1. **Skill correctness** — did the agent follow the skill instructions faithfully?
2. **Lexical graph tool usage** — were the right tools called, in the right order, with the right parameters?
3. **Tool gaps** — are there tools that should be added, merged, split, or removed?
4. **Skill gaps** — are there steps that are ambiguous, missing, or wrongly ordered?
5. **MCP server behavior** — did any tools behave unexpectedly or return unhelpful results?

---

## Step 1: Reconstruct What Happened

Review the current session to reconstruct the tool call sequence:

- Which MCP tools were called, in what order?
- What parameters were passed to each tool?
- What were the key results or errors?
- Which skill steps were followed, skipped, or reordered?

Build a timeline:
```
1. [tool_name] (server) — params summary — result summary
2. ...
```

---

## Step 2: Evaluate Lexical Graph Tool Usage

Compare the actual tool sequence against the expected sequence for the parse mode and document type used.

### Expected tool order for `neo4j-lexical-graph`

```
create_lexical_graph          # always first
  └── check_processing_status # poll until complete
list_documents                # confirm all docs ingested, get IDs
[verify_lexical_graph]        # optional: single doc spot-check only
[assign_section_hierarchy]    # optional: structured docs, not slides/page_image
[generate_chunk_descriptions] # optional: adds LLM summaries to chunks
embed_chunks
  └── check_processing_status # poll until complete
[set_active_version]          # only if re-ingesting / versioning
[clean_inactive]              # only if re-ingesting / versioning
```

For each tool in the expected sequence, assess:

| Tool | Called? | Order correct? | Params correct? | Notes |
|------|---------|---------------|-----------------|-------|
| `create_lexical_graph` | | | | |
| `check_processing_status` (after create) | | | | |
| `list_documents` | | | | |
| `verify_lexical_graph` | | | | |
| `embed_chunks` | | | | |
| `check_processing_status` (after embed) | | | | |

Flag:
- Tools called when they shouldn't have been (e.g., `verify_lexical_graph` on every doc)
- Tools that should have been called but weren't
- Tools called in the wrong order
- Parameters that were suboptimal for the doc type / parse mode

---

## Step 3: Evaluate Skill Instructions

For each skill step, assess:

| Step | Followed correctly? | Issue | Suggested fix |
|------|--------------------|----|---|
| 1. Discovery | | | |
| 2. Use case + questions | | | |
| 3. Data model | | | |
| 4. Lexical graph | | | |
| 5. Schema export + validators | | | |
| 6. Entity extraction | | | |
| 7. Verify extraction | | | |
| 8. Q&A | | | |
| 9. Report | | | |

For each issue, categorize:
- **Ambiguous instruction** — the skill wording led to the wrong behavior
- **Missing instruction** — a step or constraint wasn't in the skill
- **Wrong default** — a default (parse mode, chunk size, etc.) was inappropriate for this doc type
- **Tool not mentioned** — a useful tool exists but the skill doesn't reference it

---

## Step 4: MCP Tool Assessment

For each MCP server involved, assess the tools:

### Tool-level issues

| Tool | Server | Issue type | Description | Suggestion |
|------|--------|-----------|-------------|------------|
| | | Missing param | | |
| | | Confusing output | | |
| | | Should be merged with | | |
| | | Should be split into | | |
| | | Needs new tool | | |

Issue types:
- **Missing param** — a parameter that would be useful doesn't exist
- **Confusing output** — the tool's return value is hard to interpret
- **Wrong granularity** — tool does too much or too little
- **Merge candidate** — two tools are always called together and could be one
- **Split candidate** — one tool does too many things
- **New tool needed** — a capability gap exists in the server

---

## Step 5: Q&A Quality Assessment

For each target question answered in Step 8 of the skill:

| Question | Quality | Retrieval method used | Better method? | Root cause of gaps |
|----------|---------|----------------------|---------------|-------------------|
| | Complete / Partial / Not answered | | | |

Root causes:
- Missing entities in graph (extraction gap)
- Wrong retrieval method used
- Schema doesn't support the query pattern
- Parse mode lost information
- Chunk too large / too small

---

## Step 6: Produce Improvement Report

Save the report to `outputs/reports/<topic>_pipeline_evaluation.md`.

Structure:

```markdown
# Pipeline Evaluation — <Topic> — <Date>

## Run Summary
- Skill used: build-pdf-chatbot / develop-neo4j-graph
- Documents: <count>, <parse mode>
- Models: <embedding model>, <extraction model>

## Tool Call Timeline
[reconstructed sequence from Step 1]

## Lexical Graph Tool Assessment
[table from Step 2]

## Skill Step Assessment
[table from Step 3]

## MCP Tool Suggestions
[table from Step 4]

## Q&A Quality
[table from Step 5]

## Priority Improvements
### Immediate (fix before next test run)
1. ...

### Skill updates needed
1. ...

### MCP server changes to consider
1. ...

## Next Test Recommendation
- Document type to test next: ...
- Parse mode: ...
- Specific tool/step to focus on: ...
```
