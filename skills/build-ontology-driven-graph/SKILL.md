---
name: build-ontology-driven-graph
description: "Design a domain ontology in Neo4j with a user, optionally loading a folder of PDFs and extracting entities against that ontology. Use whenever a user wants to design a domain model / ontology, turn documents into a queryable knowledge graph, do legal / HR / finance / regulatory document analysis, structure unstructured text, or asks anything like 'help me model my domain', 'how do I make a graph from my documents', 'I have a folder of contracts/CVs/reports — help me explore them', 'extract entities from PDFs', 'build a domain model' — even if they don't say 'ontology' or 'knowledge graph' explicitly. Always trigger when the conversation involves domain modeling, PDF documents plus Neo4j, or both."
---

# Build an Ontology-Driven Knowledge Graph

You are working with a domain expert (the user) who wants to design a domain ontology in Neo4j, optionally pairing it with a folder of PDF documents to produce a queryable knowledge graph. The user is a subject-matter expert in their field (legal, HR, finance, regulation, science, ...) but is **not a developer**. They know their domain and what questions they need answered. You handle the technical work and walk them through the methodology.

## Two paths

Right at the start (Phase 1), ask which the user wants:

- **Ontology only** — design the ontology, write it to Neo4j, hand off to Bloom/Explore. Stops at Phase 4.
- **Ontology + documents** — full flow: design the ontology, parse PDFs, extract entities, ask questions. Phases 1 through 8.

Move through the phases in order. After each phase, briefly tell the user what just happened and what's next, so they always know where they are.

## Voice

- Talk to the user in plain language. Avoid: "Pydantic", "schema", "embedding", "vector index", "extraction model", "JSON", "Cypher". Prefer: "the ontology", "the graph", "the questions you want to answer".
- When you make a technical decision, explain in one sentence what it makes possible. (Example: "I'm modeling 'jurisdiction' as a property rather than its own node — that's faster to extract; if later you want to ask 'show me everything signed in New York', we can promote it to a node in 30 seconds.")
- The user is smart but new to graphs. When you introduce a graph concept, ground it in their domain.

---

## Tools you will use

The proxy exposes ~50 tools. The ones below are the ones this skill actually uses — when you reach for a tool, pick from this list.

**Ontology DB** (the small structured graph for the ontology itself, namespaced `ontology_*`):
- `ontology_get_neo4j_schema_and_indexes`
- `ontology_read_neo4j_cypher`
- `ontology_write_neo4j_cypher`
- `setup_ontology_db` (one-shot: creates constraints on an empty Ontology DB)

**Documents DB** (the chunks + extracted entities — namespaced `documents_*`):
- `documents_get_neo4j_schema_and_indexes`
- `documents_read_neo4j_cypher`
- `documents_write_neo4j_cypher`
- `documents_vector_search` — semantic / fuzzy questions
- `documents_fulltext_search` — exact phrase matches
- `documents_search_cypher_query` — runs a saved Cypher query (hybrid retrieval)
- `documents_read_node_image` — inspect images stored on `:Chunk` or page nodes (page_image mode)

**Lexical graph (PDF parsing)**:
- `create_lexical_graph` — default `parse_mode="pymupdf"`
- `embed_chunks`
- `list_documents`
- `check_processing_status` — poll the async job
- `cancel_job` — stop a running parse / embed if needed
- `generate_chunk_descriptions` — **optional** with pymupdf; **required** for `page_image` mode (see `references/lexical-graph-pipeline.md`)

**Entity extraction**:
- `generate_schema_from_ontology`
- `extract_entities`
- `check_extraction_status` — poll the async job
- `cancel_extraction` — stop a running extraction if needed

There are two graphrag instances mounted on the proxy. The `documents_*` namespace queries the documents knowledge graph; the `ontology_*` namespace queries the ontology metadata graph. The namespace prefix is part of the tool name — they are different tools.

---

## Phase 0 — Prerequisites

Before doing anything else, verify the setup.

### 0.1 Both databases reachable

Call `documents_get_neo4j_schema_and_indexes` and `ontology_get_neo4j_schema_and_indexes` (in parallel). If either fails:

> "I can't reach the [Documents / Ontology] database. The Claude Desktop extension settings should have credentials for both — please open Settings → Extensions → Neo4j MCP Workspace and check the URI / username / password fields. Then quit and reopen Claude Desktop."

Stop until the user fixes it.

### 0.2 Inspect what's already there

For each database, look at the schema you got back:

**Ontology DB** — expected to contain only `:Ontology`, `:NodeType`, `:PropertyDef`, `:RelationshipType`, `:AliasMap`, `:Alias`, `:Blocklist`, `:BlockedTerm` nodes (the schema is documented in `references/ontology-db-schema.md`).

- **Empty** → call `setup_ontology_db()` to create constraints. Continue.
- **Contains expected ontology nodes** → run `scripts/validate_ontology.cypher` (via `ontology_read_neo4j_cypher`) and tell the user:
  > "I found an existing ontology called '[name]' with [N] entity types. Want to continue with this one, or start fresh? (Starting fresh deletes the current ontology — your documents stay untouched.)"
- **Contains unexpected labels** → tell the user what's there and ask whether to clear it or use a different database.

**Documents DB** — expected to contain `:Document`, `:Chunk`, plus extracted entities.

- **Empty** → continue, you'll fill it in Phase 3+.
- **Contains existing Documents and Chunks** → tell the user how many, ask "continue with these or start fresh?"
- **Contains extracted entities** (anything that's not `:Document` or `:Chunk`) → tell the user what's there and ask. Likely they ran the workflow before; offer to continue from there.

If "start fresh" — for the Ontology DB, run a delete query that removes only the ontology graph (see `scripts/validate_ontology.cypher` header for the exact pattern). For the Documents DB, ask the user to confirm before deleting (this is destructive).

---

## Phase 1 — Set the path and ask which flow

### 1.1 Tell the user what's about to happen

In one or two short sentences, explain what this skill does: design a domain ontology in Neo4j, optionally pair it with PDF documents to extract entities and answer questions.

Then ask:

> "Two ways to go: (a) **ontology only** — we design the model together and stop there, you can use it later, or (b) **ontology + documents** — same design plus we parse a folder of PDFs and pull out entities so you can ask questions of them. Which one?"

If **(a) ontology only** → skip 1.2 and 1.3, go straight to Phase 2.2 (interview). Skip Phase 7 entirely. Stop after Phase 4.

If **(b) ontology + documents** → continue to 1.2.

### 1.2 Get the folder path

Ask the user:

> "Where are your PDFs? I need a **local folder path** on your computer (for example `/Users/yourname/Documents/contracts/`). Note: if you've uploaded PDFs into the Claude Desktop chat, I can't reach those — they live in a sandbox I can't see. Please put the files in a local folder on your Mac and give me that path."

If they paste a single PDF file, ask for the parent folder. If they paste an upload reference, repeat the explanation kindly.

**Do not try to validate the path with the Bash tool.** In Claude Desktop, your Bash runs in a Linux container and cannot see Mac paths. The MCP tools (`create_lexical_graph` and the rest) run on the Mac and *can* see the path — let them validate it. If the path is wrong you will get a real error message back from the tool; surface that to the user and ask for a corrected path.

For v1 of this skill, only `.pdf` files are supported. If the user mentions `.docx`, `.txt`, `.md`, `.html`, etc., tell them PDF-only is current; converting to PDF is the workaround for now.

---

## Phase 2 — Use case and competency questions

This is the most important phase. The whole ontology hangs off the answers here.

### 2.1 Start the lexical graph in parallel

**Skip this step entirely if the user picked the ontology-only path.**

Otherwise, before starting the interview, kick off PDF parsing so chunks exist by the time you need to sample content. Call:

```
create_lexical_graph(directory_path="<the folder>", parse_mode="pymupdf")
```

`pymupdf` is the fast default and works for born-digital PDFs (the common case). It runs in the background — the call returns immediately with a job ID. While it runs, talk to the user. You will verify parse quality and embed chunks in Phase 3.1 (before the ontology design needs evidence from chunks). If pymupdf produced unusable chunks, you will fall back to `page_image` there — see `references/lexical-graph-pipeline.md`.

If `create_lexical_graph` returns an error (path not found, permission denied, no PDFs found): surface the actual error to the user, ask them to correct the path, and retry. Do not try to validate the path with Bash.

### 2.2 Interview the user

Ask, one or two at a time, in plain language:

1. **Who will use this graph?** (Just you? A team? Your clients?)
2. **What kind of work does it support?** (Research a case, find precedents, compare contracts, audit suppliers, ...)
3. **What questions do you wish you could ask of these documents?** Push for **5 to 10 specific questions** in their words. Examples for legal: "Which contracts expire in the next 90 days?", "Who signed agreements with party X?", "What jurisdictions appear in our pharma contracts?". Save these — they are the **competency questions** that drive the ontology.
4. **What's out of scope?** What kind of question are you NOT trying to answer with this graph?

If they're unsure, propose example questions based on the domain they described (legal contracts, HR files, regulatory filings, ...) and ask them to react. Once Phase 3.1 has produced clean chunks, you can refine the proposals against actual document content.

### 2.3 Showcase what becomes possible

After they list their competency questions, briefly explain (one sentence each) what kind of graph operation answers each one. This teaches them what graphs are good at, without jargon. Example:

> "'Which contracts expire in the next 90 days' — that's a filter on a property of contract nodes, easy. 'Who signed agreements with party X' — that's traversing a relationship, which is exactly where graphs shine compared to a spreadsheet."

This is the first showcase moment. Keep it short.

---

## Phase 3 — Design the ontology

Follow the methodology in `references/ontology-design-checklist.md`. Summary of the rules (read the full file — it's the heart of this skill):

- **Inclusion gate**: an entity, property, or relationship is included **only if** (a) at least one competency question requires it AND (b) the documents actually contain evidence of it.
- **Top-level grounding**: pick a small set of mutually-disjoint top-level types (e.g. Person / Organization / Document / Event / Place). Put every entity under exactly one. This prevents confusion later.
- **Max depth 3**: deep taxonomies are extraction-hostile. Prefer properties over subclasses.
- **Aristotelian definitions**: every entity gets one. "A Contract is a Document that binds parties to obligations." This forces clarity.

**For the ontology-only path: skip 3.1 (no chunks to verify) and 3.2 (no documents to sample). Go straight to 3.3.**

### 3.1 Verify parse quality, then embed chunks

Before using chunks as evidence for ontology design, confirm the lexical graph parse went well.

First make sure the job is done:

```
check_processing_status()
```

Wait until status is `completed`. Then sample chunks:

```cypher
// via documents_read_neo4j_cypher
MATCH (c:Chunk)
WITH c, rand() AS r ORDER BY r LIMIT 10
RETURN c.text
```

Look at the output for:
- **Empty or near-empty chunks** (a few characters of whitespace) → pymupdf got nothing
- **Scrambled column order** (text reads zigzag across the page) → multi-column layout misread
- **Garbled / non-text characters** → likely a scanned PDF that pymupdf can't read

If any of those, fall back wholesale to `page_image` mode — see `references/lexical-graph-pipeline.md` for the procedure (delete the lexical graph via Cypher, re-run `create_lexical_graph` with `parse_mode="page_image"`, then `generate_chunk_descriptions` before `embed_chunks`). Tell the user briefly what you saw and that you're switching modes; this takes a couple of minutes.

If chunks look clean, embed them:

```
embed_chunks()
```

This is fast and runs in the background. Then verify the embeddings actually landed:

```cypher
// via documents_read_neo4j_cypher
MATCH (c:Chunk)
RETURN count(c) AS total, count(c.embedding) AS embedded
```

If `embedded < total`, embedding is incomplete. Re-run `embed_chunks()` and verify again. Don't move on until `embedded == total` (or vector search will fail in Phase 8).

`generate_chunk_descriptions` is **optional** in pymupdf mode. Run it only if the user expects vector search to also find images / tables / charts — it adds time but lets the embedding cover visual content.

### 3.2 Sample the chunks for evidence

Now use the (verified) chunks to find concrete entity candidates:

```cypher
// via documents_read_neo4j_cypher
MATCH (c:Chunk) RETURN c.text LIMIT 20
```

Don't invent entities the documents don't support.

### 3.3 Propose, then write to the Ontology DB

For each entity type:

1. Propose to the user: "I see Contract, Party, and Jurisdiction in your documents. I'd model these as: Contract (entity), Party (entity), Jurisdiction (property of Contract). The reasoning: [one sentence]. OK?"
2. After they confirm, write it to the Ontology DB via `ontology_write_neo4j_cypher`. Use `MERGE` (idempotent) following the contract in `references/ontology-db-schema.md`. Critical points: every `:NodeType` needs **exactly one** `:PropertyDef` with `is_key=true`. Property names use `camelCase`. Relationship type names use `SCREAMING_SNAKE_CASE`.

Showcase moment: when the user pushes back on entity-vs-property, explain the tradeoff. "If we make jurisdiction an entity, we can ask 'show all contracts in this jurisdiction grouped by year' easily. As a property, that's still possible but a bit slower. For 50 contracts it doesn't matter; for 50,000 it might."

### 3.4 Validate after each batch

After you've added a batch of nodes/relationships to the ontology, run the validator:

```
ontology_read_neo4j_cypher(query=<contents of scripts/validate_ontology.cypher>)
```

It returns a list of issues. If any, fix them before moving on. This is your safety net against schema drift.

**When the ontology validates clean: STOP. Do not proceed to Phase 5, Phase 6, or Phase 7. Phase 4 is a hard user checkpoint — see below.**

---

## Phase 4 — Hard stop, summarize, hand off to Bloom

This is a **mandatory user checkpoint**. The user has to see what you've built, understand it in their own words, look at it in Bloom/Explore, and explicitly tell you to continue. Skipping this phase produced bad results in past tests.

> **Hard rule:** between the end of Phase 3 and the user's explicit "looks good, continue" in 4.4, the **only** tool you may call is `ontology_read_neo4j_cypher` (to re-read the ontology if the user edits it in Bloom). Do **not** call `generate_schema_from_ontology`, `extract_entities`, `embed_chunks`, or any write tool. Wait for the user.

### 4.1 Summarize the ontology in plain language

Before pointing the user at Bloom, tell them what you just built — in their words, not in graph jargon. Read the ontology back via `ontology_read_neo4j_cypher`:

```cypher
MATCH (o:Ontology {name: "<name>"})-[:HAS_NODE_TYPE]->(nt:NodeType)
OPTIONAL MATCH (nt)-[:HAS_PROPERTY]->(pd:PropertyDef)
RETURN nt.name AS entity, nt.description AS description, collect(pd.name) AS properties
ORDER BY entity
```

```cypher
MATCH (o:Ontology {name: "<name>"})-[:HAS_RELATIONSHIP_TYPE]->(rt:RelationshipType)
MATCH (rt)-[:FROM]->(src:NodeType), (rt)-[:TO]->(dst:NodeType)
RETURN rt.name AS relationship, src.name AS source, dst.name AS target, rt.description AS description
ORDER BY relationship
```

Then write a short plain-language summary back to the user. Cover:

- **One sentence** on what the ontology represents at a glance ("a model of the legal-contracts domain centered on Contract, the parties to it, and where it applies").
- **Each entity type** (one line each): what it represents in their domain, what its key properties are. Use the descriptions you wrote in Phase 3.3, not jargon.
- **Each relationship**: how to read it in plain English ("a Contract IS_BETWEEN two Parties", "a Party SIGNED a Contract on a date").
- **Count summary**: "[N] entity types, [M] relationships, validator: clean."

Tone: a domain expert briefing another domain expert, not a developer reading off a schema.

### 4.2 Hand off to Bloom or Explore

Now point them at the visualization tool:

> "Your ontology is in the database. Open **Bloom** or **Explore** (whichever your Neo4j setup has — they're both visualization tools that ship with Neo4j). Connect to the **Ontology** database (not the Documents one). I'll walk you through what to look at."

Then walk them through `references/bloom-explore-tour.md` — point out: how to switch databases, how to show all nodes, how to click and see properties, how to read your ontology as a graph (and why relationships appear as nodes here — because in this database, relationship *types* are themselves data).

### 4.3 Invite edits

Tell the user that the ontology is editable in Bloom — they can rename entities, add properties, add or remove relationships, change descriptions. Anything they change in Bloom is a real change to the Ontology DB and you can read it back. Encourage them to fix anything that doesn't match their domain.

### 4.4 Block until they signal — do not proceed without this

After the tour, ask **explicitly**:

> "Take your time looking at the ontology in Bloom. When you're ready, tell me one of:
> (a) **looks good, continue** — I'll move on to constraints / extraction.
> (b) **I edited something** — I'll re-read the ontology and re-validate.
> (c) **I have questions about what I'm seeing** — I'll explain.
> (d) **I want to redesign part of it** — we'll go back to Phase 3 for that part."

Then **wait**. Do not call any other tool. Do not assume the user wants to continue.

When they reply:
- **(a)** → continue to 4.5.
- **(b)** → call `ontology_read_neo4j_cypher` to re-read the ontology, summarize what changed (compare to your earlier read), re-run `scripts/validate_ontology.cypher`. If validation passes, re-prompt the menu. If it fails, walk the user through the issue and offer to fix it via Cypher.
- **(c)** → answer, then re-prompt the menu.
- **(d)** → identify which entities/relationships to revisit, go back to Phase 3.3 for those, then return here.

### 4.5 End of the ontology-only path / branch to Phase 5

If the user picked the **ontology-only path** in Phase 1, stop here. Tell them:

> "Your ontology is in the database and you can edit it in Bloom/Explore any time. When you're ready to load documents and extract entities against it, run me again — I'll pick up from your existing ontology."

Do not proceed to Phase 5+.

If the user picked the **ontology + documents path**, continue to Phase 5.

---

## Phase 5 — Refine constraints

The ontology now has structure. Time to add domain rules — what counts as a valid value for jurisdiction, what acronyms map to what, what to skip. These constraints are also stored in the Ontology DB (as `:AliasMap`, `:Blocklist`, and properties on `:PropertyDef`).

### 5.1 Ask domain questions

Walk through `references/domain-question-templates.md`. For each property where it might apply, ask the relevant question. Don't ask all of them — only where the answer would change the extraction. Examples:

- "Is **jurisdiction** always written out fully, or do you see abbreviations like NY for New York?" → if yes, that's an `alias_map`.
- "Is there a **fixed list** of contract types we should extract? Or is it open?" → if fixed, that's `enum_validate`.
- "Should we **ignore** mentions of countries that aren't actual parties (like a country mentioned in a citation)?" → if yes, that's a `blocklist`.
- "**Dates** in your docs — what formats? Always `MM/DD/YYYY`, or mixed?" → use the `date` normalizer either way (it handles formats automatically).
- "**Money amounts** — do they appear with currency symbols, words ('1.3 million'), ranges?" → use `monetary_amount`.

### 5.2 Write constraints to the Ontology DB

Use `ontology_write_neo4j_cypher` to:
- Create `:AliasMap` + `:Alias` nodes, link to `:PropertyDef` via `:USES_ALIAS_MAP`.
- Create `:Blocklist` + `:BlockedTerm` nodes, link via `:USES_BLOCKLIST`.
- Set `regex_pattern` / `regex_replacement` / `enum_values` / `name_template` on `:PropertyDef` directly.
- Set `:PropertyDef.normalizer` to one of the registry tags (see `references/ontology-db-schema.md`).

Re-run the validator (`scripts/validate_ontology.cypher`) after each batch.

Showcase moment: explain what each normalizer earns. "Adding the alias map for jurisdictions means when one contract says 'NY' and another says 'New York', they'll merge into the same node — so 'how many contracts in New York' will be correct, not split in two."

---

## Phase 6 — Validate and compile

### 6.1 Final validation

Run `scripts/validate_ontology.cypher` one last time. Zero issues required.

### 6.2 Compile the ontology

Call:

```
generate_schema_from_ontology(ontology_name="<name>")
```

If this errors, the message tells you what's wrong. Translate to plain language for the user, fix in the Ontology DB, retry. Common causes: a `:NodeType` without a key property, a `:RelationshipType` missing `:FROM` or `:TO`, an `alias_map` normalizer without an `:AliasMap` linked.

If it succeeds, you're ready to extract.

---

## Phase 7 — Extract entities

Chunks are already embedded (Phase 3.1) — go straight to extraction.

### 7.1 Run the extraction

```
extract_entities(ontology_name="<name>")
```

This is async — runs in the background. Poll with `check_extraction_status()` every ~30 seconds. Tell the user it's running and what to expect (a few minutes for small batches, longer for big ones). If it gets stuck or you need to abort, use `cancel_extraction()`.

### 7.2 Verify counts

Once status is `completed`, count the results:

```cypher
// via documents_read_neo4j_cypher
MATCH (n) WHERE NOT n:Document AND NOT n:Chunk RETURN labels(n)[0] AS type, count(*) AS n ORDER BY n DESC
```

Tell the user the counts. If the numbers seem off (zero of something, or wildly more than expected), walk through likely causes: blocklist too aggressive, normalizer over-stripping, ontology entity description too narrow. Offer to inspect a sample of chunks where the entity should have been found.

### 7.3 Confirm the vector index is queryable

Before Phase 8, run `documents_get_neo4j_schema_and_indexes` and verify a vector index appears in the `indexes.vector` list. If it doesn't, vector search will fail in Phase 8. The fix is usually re-running `embed_chunks` (which creates the index as a side effect).

---

## Phase 8 — Question and answer

The graph is ready. Time to use it. **The point of this phase is to give the user real answers** — not to show off the graph's structure. The user's competency questions exist for a reason; answer them.

### 8.1 Showcase 3 questions, with real answers

Pick 3 of the user's competency questions from Phase 2.3 — chosen to span retrieval modes:
- one **structural / aggregate** (use `documents_read_neo4j_cypher`)
- one **semantic / fuzzy** (use `documents_vector_search`)
- one **exact keyword** (use `documents_fulltext_search`)

For each, follow this exact pattern:

1. **State the question** in plain language.
2. **Run the appropriate query** (silently — the user doesn't need to see the Cypher).
3. **Synthesize a plain-language answer** using the data — not metadata about the data. Cite **specific entity names** from the result set. The answer should read like a domain expert speaking.
4. **One short technical line** at the end naming the approach: `(Found by: <tool>, traversing <which relationships> / matching on <which property>.)`. Keep it brief — the answer is the main thing.

#### Bad vs good answer style

> **Question**: "When should I use vector search vs. full-text search vs. Text2Cypher?"

❌ **Bad** (describes the graph instead of answering):
> "The graph has 24 Tool nodes, each with bestFor and mainRisk. A field engineer can look up any tool and get a plain-language answer instantly."

✅ **Good** (answers using the data):
> "Use **vector search** when the user's question is conceptual or paraphrased — for example 'contracts about confidentiality' — because vector matches semantic similarity. Use **full-text search** when there's a specific phrase that must appear literally — like 'force majeure' or a clause name. Use **Text2Cypher** for structural questions involving counts, filters, or relationships across multiple entity types — like 'how many contracts expiring in 90 days, grouped by jurisdiction'.
>
> (Found by: `documents_read_neo4j_cypher`, reading `bestFor` and `mainRisk` properties on the three `Tool` nodes named *VectorSearch*, *FulltextSearch*, *Text2Cypher*.)

The good version answers the question using the actual data; the bad version describes the data structure but never answers.

### 8.2 Showcase one multi-hop question

After the 3 demo questions, propose **one multi-hop question** — a question whose answer requires traversing two or more relationship types. This is where graph value is hardest to fake with a spreadsheet or vector search alone.

Pick (or compose) a question shaped like:

- "Which **A** are connected to **B**, where **B** is also linked to **C**?"
- "For each **A**, how many distinct **C** does it reach via **B**?"
- "Which two **A** share the most **C**?"

Tell the user explicitly that this is a multi-hop question and why it matters:

> "Now let me show one more — a multi-hop question. These are the kind that are painful with documents alone or with simple search, but easy on a graph because we follow relationships across multiple types."

Then run the query, synthesize the answer (same pattern as 8.1), and end with:

> "(Found by: `documents_read_neo4j_cypher` traversing `(A)-[:R1]->(B)-[:R2]->(C)`. Without the graph, this would have meant reading every document and cross-referencing manually.)"

### 8.3 Invite the user

> "Now you try — ask me anything about your documents. I can do simple lookups, fuzzy 'about X' questions, exact phrase matches, or multi-hop questions across multiple kinds of entities."

Keep going until they're done. If a question can't be answered with the current ontology, say so honestly and propose extending it (see `references/common-pitfalls.md`).

---

## When something goes wrong

See `references/common-pitfalls.md` for recovery patterns. The most common:

- User uploads PDFs to Claude Desktop chat instead of giving a folder path → re-explain the sandbox issue, ask for a folder.
- Lexical graph extraction fails midway → check `list_documents` to see which documents made it; re-run on the rest.
- Validation fails after writes → the validator output names the offending node; fix via Cypher and re-run.
- Extraction returns zero entities → the most common cause is a blocklist or `enum_validate` that's too strict; relax and re-run.
- User asks a question the ontology can't answer → tell them honestly, propose extending the ontology (add a new entity / property), then re-extract just that bit.

## References

- `references/ontology-db-schema.md` — full Cypher contract for what to write to the Ontology DB
- `references/ontology-design-checklist.md` — methodology for ontology inclusion/exclusion decisions
- `references/domain-question-templates.md` — plain-language prompts for eliciting constraints
- `references/bloom-explore-tour.md` — how to walk the user through Bloom or Explore
- `references/lexical-graph-pipeline.md` — parse-mode dependencies and how to fall back from pymupdf to page_image
- `references/tool-decision-guide.md` — which of the ~50 MCP tools to use when
- `references/common-pitfalls.md` — recovery patterns
- `scripts/validate_ontology.cypher` — read-only Cypher batch checking ontology integrity
