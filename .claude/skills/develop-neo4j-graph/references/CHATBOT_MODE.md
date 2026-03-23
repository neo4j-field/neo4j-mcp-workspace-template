# CHATBOT MODE — Use Case Framing and Q&A Output

Used during **Step 2** (use case framing) and **Step 8** (Q&A output) of the `develop-neo4j-graph` skill when MODE = CHATBOT.

---

## Step 2: Use Case Framing (CHATBOT mode)

1. Ask the user for their use case context: domain, audience, what decisions or questions the chatbot should support
2. Based on the data content and use case, propose **5–8 realistic target questions** a user might ask the chatbot. Questions should:
   - Be specific and answerable from the available data (CSV, PDF, or both)
   - Cover different query types: factual lookup, comparison, relationship traversal, aggregation
   - Reflect the stated use case
3. Present the proposed questions and ask the user to:
   - Confirm, edit, or remove questions
   - Add questions you may have missed
4. Finalize the question list — **these become the validation targets for the entire pipeline**

During Step 3 (data modeling), map each confirmed question to the nodes/relationships that will answer it. Note any questions the current model cannot address — these become known gaps.

---

## Step 8: Answer Confirmed Questions (CHATBOT mode)

For each confirmed question from Step 2, answer it using `neo4j-graphrag` tools. Try the most appropriate retrieval method first, then note what worked.

Before running vector or fulltext search, get the index name with `get_neo4j_schema_and_indexes`.

### Retrieval methods

| Question type | Preferred method | MCP tool |
|---------------|-----------------|----------|
| Semantic / open-ended | Vector search | `vector_search` |
| Keyword / name lookup | Fulltext search | `fulltext_search` |
| Relationship traversal / structured | Cypher | `read_neo4j_cypher` |
| Complex / multi-hop | Graph-grounded | `search_cypher_query` |
| Inspect visual source of an answer | Read node image | `read_node_image` |

### Using `read_node_image`

All parse modes can produce nodes with images:
- `page_image` — every Chunk node is a full page image
- `pymupdf`, `docling`, `vlm_blocks` — Image and Table element nodes may contain images

Use `read_node_image` with the node's `elementId` when a retrieval result references a node that likely has visual content. Valuable for:
- Verifying the answer came from the right source
- Questions about diagrams, tables, or pipeline steps where the image itself is the answer
- Debugging unexpected or low-quality answers by inspecting what the VLM saw

### Per-question record

For each question, record:
- **Question** — the confirmed question text
- **Method used** — vector / fulltext / cypher / combined / image
- **Query** — the actual query or Cypher used
- **Answer** — the result from the graph
- **Image inspected** — yes/no, and what it showed
- **Quality** — Complete / Partial / Not answered
- **Improvement note** — what would make this answer better (more data, schema change, better chunking, different parse mode)

---

## Step 9: Generate Chatbot Report

Save to `outputs/reports/<topic>_chatbot_report.md`.

```markdown
# Chatbot Report — <Topic>

## Source Data
- List each source: filename/path, type (CSV/PDF), parse mode (PDF only), record/chunk count

## Use Case
<User-stated use case and audience>

## Graph Data Model
<Mermaid diagram>
<Description of each node and relationship>

## Target Questions and Answers

### Q1: <question>
- **Method**: <vector / fulltext / cypher / image>
- **Query**: <query used>
- **Answer**: <answer from graph>
- **Quality**: Complete / Partial / Not answered
- **Improvement**: <note>

[repeat for each question]

## Extraction Quality (if PDF data present)
- Entity counts per label
- Duplicate analysis
- Entity-to-chunk link count

## Gaps and Limitations
- Questions not answered and why
- Schema gaps
- Parse mode observations (PDF)

## Recommended Next Steps
- Validator improvements
- Schema refinements
- Additional data sources
- Alternative parse modes to try
```
