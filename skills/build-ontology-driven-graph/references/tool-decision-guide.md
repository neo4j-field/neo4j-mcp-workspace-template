# Tool decision guide

Which of the ~50 MCP tools to use at each phase of this skill. Tools fall into three categories: **the core path** (use these every run), **occasional** (use when relevant), and **out of scope** (don't use — they belong to other workflows like CSV ingestion or developer-facing schema export).

## Core path — by phase

### Phase 0 — Prerequisites
| Tool | When |
|---|---|
| `documents_get_neo4j_schema_and_indexes` | Always — at start, to verify connection and inspect existing data |
| `ontology_get_neo4j_schema_and_indexes` | Always — same, on the Ontology DB |
| `setup_ontology_db` | Only if Ontology DB is empty (creates uniqueness constraints) |

### Phase 1 — Set the path and ask which flow
No MCP tools, no Bash. Just ask the user which path (ontology only vs ontology + documents) and, for the documents path, collect the folder path. **Do not** validate the path with Bash — in Claude Desktop, Bash runs in a sandbox that can't see Mac paths. Hand the path to `create_lexical_graph` in Phase 2 and surface its error if the path is wrong.

### Phase 2 — Lexical graph (parallel) — skip for ontology-only
| Tool | When |
|---|---|
| `create_lexical_graph` | Kicks off async parsing — always with `parse_mode="pymupdf"` initially |
| `check_processing_status` | Poll every ~30s during parsing |
| `list_documents` | After parsing — verify which PDFs made it in |

### Phase 3 — Ontology design
| Tool | When |
|---|---|
| `check_processing_status` | At the start of 3.1, confirm `create_lexical_graph` finished |
| `documents_read_neo4j_cypher` | 3.1 sample chunks for parse-quality check; 3.2 sample chunks for evidence; verify embedding count after embed_chunks |
| `embed_chunks` | 3.1 after parse-quality check passes (mandatory before Phase 8) |
| `documents_write_neo4j_cypher` | Only if pymupdf parse was bad — wipe the lexical graph before re-running with `page_image` (see `references/lexical-graph-pipeline.md`) |
| `generate_chunk_descriptions` | Required if falling back to `page_image`; optional otherwise |
| `ontology_write_neo4j_cypher` | Write `:NodeType`, `:PropertyDef`, `:RelationshipType` nodes |
| `ontology_read_neo4j_cypher` | Read back, run the validator script, list current ontology elements |

### Phase 4 — Bloom/Explore handoff
| Tool | When |
|---|---|
| `ontology_read_neo4j_cypher` | After user edits in Bloom — re-read ontology, validate |

### Phase 5 — Constraints
Same write/read tools as Phase 3, plus:
| Tool | When |
|---|---|
| `ontology_write_neo4j_cypher` | Add `:AliasMap`, `:Alias`, `:Blocklist`, `:BlockedTerm` nodes; set normalizer fields on `:PropertyDef` |
| `ontology_read_neo4j_cypher` | Run validator after each batch |

### Phase 6 — Compile
| Tool | When |
|---|---|
| `ontology_read_neo4j_cypher` | Final validation pass with `scripts/validate_ontology.cypher` |
| `generate_schema_from_ontology` | Compile to Pydantic schema (the entity-graph server reads this) |

### Phase 7 — Extract (skipped for ontology-only path)
| Tool | When |
|---|---|
| `extract_entities` | Pass `ontology_name` — runs async. Embedding already done in Phase 3.1. |
| `check_extraction_status` | Poll every ~30s during extraction |
| `cancel_extraction` | Only if user explicitly aborts |
| `documents_get_neo4j_schema_and_indexes` | Confirm the vector index is queryable before Phase 8 |
| `documents_read_neo4j_cypher` | Verify entity counts after extraction completes |

### Phase 8 — Q&A
| Tool | Use for |
|---|---|
| `documents_vector_search` | Semantic / fuzzy questions: "contracts about confidentiality", "documents discussing climate risk" |
| `documents_fulltext_search` | Exact-keyword questions: "contracts mentioning 'force majeure'", "find ESCO references" |
| `documents_read_neo4j_cypher` | Structural / aggregate / relational: counts, joins, "expiring in 90 days", "all parties of contract X" |
| `documents_read_node_image` | If a chunk has a `pageImage` link (vlm parse modes) and the user asks about a figure |

## Occasional — use when relevant

| Tool | Use case |
|---|---|
| `documents_search_cypher_query` | Look up saved/predefined queries (not commonly used in this skill) |
| `generate_chunk_descriptions` | Phase 3.1 only. **Required** when falling back to `page_image`. Optional with `pymupdf` — adds short text descriptions of images and tables so vector search covers visual content. See `references/lexical-graph-pipeline.md`. |
| `assign_section_hierarchy` | Group chunks by section/heading — useful for long structured documents (optional Phase 3 enhancement) |
| `verify_lexical_graph` | Generates a Markdown reconstruction of a parsed document. The output isn't accessible to Claude Desktop's sandbox, so don't rely on it during the skill — the Phase 3.1 chunk-sampling check is the in-skill substitute. |
| `delete_document` | Surgical — if the user wants to remove one PDF from the Documents DB without re-running everything |
| `chunk_lexical_graph` | Re-chunk an existing document with different parameters (rare) |
| `cancel_job` | Generic job cancellation — prefer `cancel_extraction` for extraction jobs |
| `clean_inactive` | Cleanup of orphaned background jobs — maintenance only |
| `documents_write_neo4j_cypher` | Surgical edits to extracted data (e.g. fix a single misnormalized name). Use sparingly — most data should come from `extract_entities`. |

## Out of scope — don't use

These tools belong to other workflows and would confuse the lawyer/SME path. **Don't call them unless the user explicitly asks for one of these things.**

| Tool | Why it's out of scope here |
|---|---|
| `convert_schema` | File-based extraction path. We use `generate_schema_from_ontology` (graph-based) instead. |
| `validate_data_model` / `validate_node` / `validate_relationship` | These validate the data-modeling server's JSON format, not our Ontology DB graph. Use `scripts/validate_ontology.cypher` instead. |
| `list_example_data_models` / `get_example_data_model` | Developer reference for example JSON data models. Not relevant to Ontology DB design. |
| `_export_to_pydantic_models` (note: prefixed with `_`) | Renamed/hidden by the proxy — would conflict with the correct schema export path. |
| `export_to_arrows_json` / `load_from_arrows_json` | Arrows.app interchange format — for visual data modeling export, not our flow. |
| `export_to_owl_turtle` / `load_from_owl_turtle` | TTL/OWL format — we store the ontology natively in the graph instead. |
| `export_to_neo4j_graphrag_pkg_schema` / `load_from_neo4j_graphrag_pkg_schema` | The `neo4j-graphrag` Python package schema format — not needed in this skill. |
| `ingest_csv_into_neo4j` / `execute_write_cypher_query` | CSV ingestion path — separate from PDF/lexical-graph workflow. |
| `get_node_cypher_ingest_query` / `get_relationship_cypher_ingest_query` / `get_constraints_cypher_queries` | Generated Cypher templates for CSV ingestion — not used here. |
| `get_mermaid_config_str` | Mermaid diagram generation for data models — useful for documentation but not needed in this user-facing flow. |
| `set_active_version` | Versioning of data models — not used in v1. |

## Tool selection in Phase 8 — decision tree

When the user asks a question, pick the tool by question shape:

```
Question contains a specific keyword the document would use literally?
  → documents_fulltext_search

Question is conceptual / fuzzy / paraphrased ("about", "regarding", "related to")?
  → documents_vector_search

Question involves counts, filters, joins, aggregates, or relationships between entities?
  → documents_read_neo4j_cypher (write a Cypher query)

Question requires combining multiple of the above?
  → Start with read_neo4j_cypher to find candidate entities, then vector_search for context
```

After answering, briefly tell the user which tool you used and why — one sentence. This is part of the showcase.

Examples:

| Question | Tool | Why |
|---|---|---|
| "How many contracts do we have?" | `documents_read_neo4j_cypher` | Aggregate count |
| "Which contracts mention force majeure?" | `documents_fulltext_search` | Specific keyword |
| "What contracts are about IP licensing?" | `documents_vector_search` | Conceptual match |
| "Show all parties of the Acme MSA and their other contracts" | `documents_read_neo4j_cypher` | Multi-hop relationship traversal |
| "Find contracts similar to this one" | `documents_vector_search` then `documents_read_neo4j_cypher` | Semantic seed, then explore neighborhood |
