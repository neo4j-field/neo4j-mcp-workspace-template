# Common pitfalls and recovery patterns

When something goes wrong, use these patterns. Don't dig further on your own — surface the issue to the user in plain language and offer the fix.

## User uploaded PDFs to Claude Desktop chat instead of giving a folder path

**Symptom:** User says "I uploaded the files" but no folder path. You see attachment markers but no readable filesystem path.

**Recovery:**
> "I can't reach files uploaded into the Claude Desktop chat — those live in a sandbox the MCP servers can't see. Could you put your PDFs in a local folder on your computer and give me the path? For example `/Users/yourname/Documents/contracts/`."

If they keep trying to upload, gently repeat. Don't give up and try to work around it — there is no workaround.

---

## `create_lexical_graph` fails or stalls

**Symptom:** `check_processing_status` shows error or hasn't progressed in minutes.

**Recovery:**
1. Run `list_documents` — see what made it in.
2. If most documents succeeded, ask the user if they want to continue with what's there or retry the failures.
3. If everything failed, check the most likely causes:
   - PDF is encrypted/password-protected
   - PDF is image-only (no text layer) — would need a different parse mode (`docling` or `vlm_blocks`), but for v1 the skill assumes pymupdf works
   - File path was wrong / files moved / permissions
4. Tell the user what you found and what to try.

If specific documents fail, offer to skip them and continue with the rest.

---

## Validator returns errors

**Symptom:** `scripts/validate_ontology.cypher` returns one or more rows.

**Recovery:** Read the `message` field of each issue — it's written for humans. Translate to plain language for the user only if needed. The most common errors and their fixes:

| Check | Fix |
|---|---|
| `missing_key_property` | Add a `:PropertyDef` with `is_key=true` to the NodeType. Choose the most identifying field (name, title, identifier). |
| `multiple_key_properties` | `SET key.is_key = false` on all but the most identifying one. |
| `missing_from_endpoint` / `missing_to_endpoint` | `MATCH` the source/target NodeType and `MERGE (rt)-[:FROM]->(src)` (or `:TO`). |
| `endpoint_outside_ontology` | Either add the endpoint NodeType to this ontology (`MERGE (o)-[:CONTAINS]->(nt)`) or change the relationship to use a NodeType that *is* in this ontology. |
| `invalid_property_type` | `SET pd.type = "STRING"` (or INTEGER/FLOAT/BOOLEAN). Most things are STRING. |
| `invalid_normalizer_tag` | The normalizer tag is misspelled or unknown. Check `references/ontology-db-schema.md` for the registry. |
| `alias_map_missing_link` / `blocklist_missing_link` | Create the AliasMap/Blocklist and `:USES_ALIAS_MAP` / `:USES_BLOCKLIST` link, OR remove the normalizer if it's not actually wanted. |
| `regex_normalize_missing_config` / `regex_skip_missing_config` | Set `pd.regex_pattern` (and `pd.regex_replacement` for normalize). |
| `enum_validate_missing_values` | Set `pd.enum_values = [...]` or remove the normalizer. |

After fixing, re-run the validator until it returns zero rows.

---

## `generate_schema_from_ontology` errors

**Symptom:** The compile step fails after validation passes.

**Recovery:** The error message names the issue. Most common:

- `"Ontology 'X' not found"` — typo in the ontology name. Check via `MATCH (o:Ontology) RETURN o.name`.
- `"NodeType 'X' has no PropertyDef with is_key=true"` — validator should have caught this. Re-run validator and fix.

Translate to plain language for the user, fix in the ontology, retry.

---

## `extract_entities` returns zero entities (or far fewer than expected)

**Symptom:** Extraction completes but `MATCH (n) WHERE NOT n:Document AND NOT n:Chunk RETURN count(n)` is 0 or surprisingly low.

**Recovery diagnostic flow:**

1. **Are there chunks at all?** `MATCH (c:Chunk) RETURN count(c)`. If 0, the lexical graph wasn't built. Re-run `create_lexical_graph`.

2. **Were the chunks processed?** `MATCH (c:Chunk) WHERE c.processed = true RETURN count(c)` (or whatever the marker is — verify schema). If 0, extraction didn't run properly.

3. **Is the ontology too narrow?** Sample a chunk's text and ask: would I (as a domain expert) find the entities in here? If yes but the extractor didn't, look at:
   - Entity descriptions — too vague? Too narrow? An LLM-friendly description matters a lot.
   - Required fields — if `is_key` property is required but rarely appears in the text, entities get dropped.
   - Normalizers — `enum_validate` with too narrow a list, or `blocklist` with too many terms, or `regex_skip` matching too broadly.

4. **Most likely cause: blocklist or enum_validate too aggressive.** Walk the user through the constraints; relax as needed; re-extract.

**Don't re-run the whole extraction if you can avoid it.** Extraction is the slow step. Diagnose first, then decide.

---

## User asks a question the ontology can't answer

**Symptom:** In Phase 8, the user asks something that requires an entity type or relationship that's not in the ontology.

**Recovery:**
> "Your ontology doesn't currently capture [thing]. To answer that question, we'd need to add [entity / property / relationship] and re-extract. Want me to do that? It'll take a few minutes."

If yes:
1. Add the new ontology element (Cypher write).
2. Run validator + `generate_schema_from_ontology`.
3. Re-run `extract_entities` — it will pick up new types but won't re-extract existing ones (idempotent).
4. Answer the question.

This is a good moment — the user sees the ontology is alive and extensible, not frozen.

---

## Bloom or Explore not loading anything

**Symptom:** User says "I see nothing".

**Recovery:**
1. Confirm they're on the right database (Ontology DB for Phase 4, Documents DB for Phase 7).
2. Run `ontology_get_neo4j_schema_and_indexes` (or documents) to verify there's data.
3. If data exists but UI is blank, suggest they refresh / reconnect / try a basic query like `MATCH (n) RETURN n LIMIT 10`.
4. If still nothing, the issue is likely browser- or session-side — ask them to fully close and reopen their Neo4j Workspace tab.

---

## Two databases configured but pointing at the same place

**Symptom:** User has set Ontology DB and Documents DB to the same URI + same database name. Ontology nodes mix with extracted data.

**Recovery:**
> "It looks like your Ontology and Documents databases are the same place — they should be separate so the ontology metadata doesn't mix with your extracted entities. Two options:
> - **Cleanest**: use two different Neo4j instances (or two databases within one instance).
> - **Quick demo**: use the same instance and prefix-separate by labels (less clean — recommend only for testing).
>
> To fix: open Settings → Extensions → Neo4j MCP Workspace, set distinct values for the Ontology DB URI/database, and restart Claude Desktop."

---

## User wants to "start over"

**Symptom:** Mid-flow, user says "scrap all this and start fresh".

**Recovery:** Confirm what they want to delete:
- Just the ontology? → `DELETE` ontology graph from Ontology DB (see deletion query in `ontology-db-schema.md`).
- Ontology + extracted entities (keep documents/chunks)? → Delete ontology + `MATCH (n) WHERE NOT n:Document AND NOT n:Chunk DETACH DELETE n` on Documents DB.
- Everything? → Both above + `MATCH (d:Document) DETACH DELETE d` and `MATCH (c:Chunk) DETACH DELETE c`.

Always confirm before destructive operations. Use `ontology_write_neo4j_cypher` / `documents_write_neo4j_cypher` once confirmed.

---

## You skipped Phase 4 and started extracting

**Symptom:** You finished Phase 3 (ontology validates clean) and went straight to `generate_schema_from_ontology` or `extract_entities` without summarizing the ontology to the user, without pointing them at Bloom, and without waiting for their explicit "looks good, continue" signal.

**Why this is a problem:** The user has no chance to review or correct the ontology before extraction runs against it. Extraction is the slow step — running it on a wrong ontology wastes minutes and produces bad data. Also: the user is the domain expert; the ontology must match their mental model, not yours.

**Recovery:**

1. Stop immediately. Do not call any further extraction or write tools.
2. If extraction has started, decide whether to wait for it or call `cancel_extraction()`. If it's only been a few seconds, cancel.
3. Now do Phase 4 properly:
   - Read the ontology back via `ontology_read_neo4j_cypher` (entity types with properties; relationship types with from/to).
   - Summarize in plain language (Phase 4.1) — entity types in their domain words, relationships read as English sentences, count summary.
   - Hand off to Bloom (Phase 4.2) — walk them through the visualization tour.
   - Wait for their explicit menu signal (Phase 4.4). Do not call any tool other than `ontology_read_neo4j_cypher` until they reply.
4. If they signal changes, apply them, re-validate, re-prompt.
5. Only after explicit "(a) looks good, continue" → proceed to Phase 5.

**Prevention:** Phase 4 is a hard stop, not a soft suggestion. Read its opening directive every time. Between Phase 3 and the user's "(a)" in Phase 4.4, the only allowed tool call is `ontology_read_neo4j_cypher`.

---

## You're not sure which Neo4j database the user is on

**Symptom:** User says "I see X" but X looks like it's from the wrong DB.

**Recovery:** Don't guess. Run schema queries on both:

```
documents_get_neo4j_schema_and_indexes()
ontology_get_neo4j_schema_and_indexes()
```

Compare what comes back to what they're describing. Then tell them which DB they're looking at and how to switch.
