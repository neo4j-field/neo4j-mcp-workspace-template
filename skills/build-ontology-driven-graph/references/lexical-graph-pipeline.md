# Lexical graph parse modes — pipeline and fallback

`create_lexical_graph` accepts a `parse_mode` parameter. The skill defaults to `pymupdf` (fast, works for most born-digital PDFs) and falls back to `page_image` if pymupdf produces unusable chunks.

You only need this file if pymupdf produced bad chunks in Phase 3.1. For the common case (born-digital PDFs), pymupdf → embed_chunks is enough.

## Modes

| Mode | When to use | Pipeline after `create_lexical_graph` |
|---|---|---|
| `pymupdf` (default) | Born-digital PDFs with selectable text — modern contracts, briefs, reports | `embed_chunks` → done. Optional: `generate_chunk_descriptions` if you want vector search to also surface images / tables (extra time, only useful when visual content matters). |
| `page_image` | Scanned PDFs / image-only docs / pymupdf produced empty or scrambled chunks | **`generate_chunk_descriptions` → `embed_chunks`** — page_image chunks have minimal text on their own; descriptions are what gets embedded. Skipping descriptions = vector search returns nothing useful. |

`docling` and `vlm_blocks` exist as alternative parsers (rich tables / mixed layouts) but are out of scope for this skill — fall back from pymupdf goes directly to page_image.

## How to detect a bad pymupdf parse

In Phase 3.1, sample chunks via `documents_read_neo4j_cypher`:

```cypher
MATCH (c:Chunk)
WITH c, rand() AS r ORDER BY r LIMIT 10
RETURN c.text
```

A bad parse looks like one of:

- **Empty or near-empty chunks** — a few characters of whitespace, no real text. pymupdf got nothing extractable (likely a scanned PDF).
- **Scrambled column order** — text reads zigzag across the page (e.g. 2-column layout misread as a single flow that hops between columns). Watch for sentences that don't grammatically continue.
- **Garbled / non-text characters** — boxes, question marks, mojibake. Often a font-encoding issue on a scanned-then-OCR'd PDF.

If chunks look fine — coherent sentences, normal paragraph structure — pymupdf worked. Just embed.

## Falling back to `page_image`

This is wholesale: the entire corpus re-parses with the new mode (the lexical graph tools don't currently support per-document parse modes). Tell the user briefly what you saw and that you're switching modes; expect a couple of minutes for typical document sets.

### Step 1 — wipe the existing lexical graph

Use `documents_write_neo4j_cypher`:

```cypher
MATCH (n)
WHERE n:Chunk OR n:Document OR n:Page OR n:Image OR n:Table OR n:Section
DETACH DELETE n
```

(Adjust the label list if `list_documents` reveals other lexical graph node types in your environment. The set above covers what `create_lexical_graph` produces in pymupdf and page_image modes.)

### Step 2 — re-parse with page_image

```
create_lexical_graph(directory_path="<same folder>", parse_mode="page_image")
```

Wait for it via `check_processing_status()`.

### Step 3 — generate chunk descriptions (required for page_image)

```
generate_chunk_descriptions()
```

This is the step that gives page_image chunks something embeddable. Skip it and `embed_chunks` will produce empty embeddings — vector search in Phase 8 will return nothing.

### Step 4 — embed and verify

```
embed_chunks()
```

```cypher
// via documents_read_neo4j_cypher
MATCH (c:Chunk)
RETURN count(c) AS total, count(c.embedding) AS embedded
```

Continue when `embedded == total`.

### Step 5 — sanity-check the new chunks

```cypher
MATCH (c:Chunk)
WITH c, rand() AS r ORDER BY r LIMIT 10
RETURN c.text
```

In page_image mode, chunk text may still be sparse — that is normal. The signal here is that descriptions are present (you can also inspect them: `MATCH (c:Chunk) RETURN c.description LIMIT 10`) and that `documents_read_node_image` works on a sample chunk.

## When to use `generate_chunk_descriptions` with pymupdf

Optional. The function generates text descriptions for image and table nodes attached to chunks. Run it if the user expects vector search to also find images / tables / charts. Skip it for text-only Q&A — saves a few minutes.

## When something is still wrong after page_image fallback

If chunks are still bad after page_image + descriptions, the PDFs may need a parser the skill doesn't currently support (`docling` or `vlm_blocks`). Tell the user honestly, and offer to either (a) try those modes manually with `create_lexical_graph(parse_mode="docling")` after wiping again, or (b) ask the user for a different document set.
