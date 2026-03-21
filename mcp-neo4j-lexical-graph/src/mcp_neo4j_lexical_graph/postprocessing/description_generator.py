"""Post-processing: generate text descriptions for visual content using VLM.

Creates meaningful text representations so that embedding models can produce
useful vectors. Supports three source modes:
  - docling: image/table data on Chunk nodes
  - pymupdf: image data on linked Image/Table nodes
  - page_image: full page images + extracted text on Page nodes
"""

from __future__ import annotations

import asyncio
from typing import Any

import litellm
import structlog
from neo4j import AsyncDriver
from pydantic import BaseModel, Field

logger = structlog.get_logger()

IMAGE_PROMPT = """\
You are analysing a visual element from the document "{document_name}".
{section_context_line}{caption_line}
IMPORTANT: First decide whether this image carries meaningful content (a chart, graph, \
diagram, schematic, screenshot, photograph, map, infographic, or any other informative visual). \
If it is a logo, header, footer, decorative element, watermark, icon, or page furniture \
with no standalone informational value, respond with exactly: \
"Non-informative image: [brief label, e.g. company logo, page header]" and stop. \
Do not fabricate content.

If it carries meaningful content, write a description that enables semantic similarity search — \
someone querying for the information, concepts, or insights this image conveys \
should be able to find it.

Extract and describe:
1. What the image shows or communicates (subject matter, purpose, domain)
2. What is being compared, measured, or illustrated (entities, variables, categories, steps)
3. Key findings, values, relationships, or conclusions visible in the image
4. The visual type (bar chart, line graph, diagram, flowchart, photograph, map, screenshot, etc.)
5. Any readable text, labels, legends, or annotations

Write a single dense paragraph using the vocabulary and domain of the document. \
Express meaning and content — avoid vague visual vocabulary like "blue bar" or "arrow pointing right". \
Only describe what you can actually read or see — do not infer or fabricate."""

TABLE_PROMPT = """\
You are analysing a table from the document "{document_name}".
{section_context_line}{caption_line}
{table_content_section}
Your goal is to write a description that enables semantic similarity search — \
someone querying for the data, comparisons, or information this table presents \
should be able to find it.

Extract and describe:
1. What the table covers (subject matter, purpose, domain)
2. What is being compared or reported (rows, columns, categories, time periods, entities)
3. Key values, patterns, or notable differences visible in the data
4. Any conclusions or significance the table supports in the document context

Write a single dense paragraph using the vocabulary and domain of the document. \
Do not describe table structure — express the content and meaning."""

PAGE_PROMPT = """\
You are analysing page {page_number} of the document "{document_name}".
The page image is provided along with the text extracted via OCR/PDF parsing.

Extracted text:
---
{extracted_text}
---

Using both the page image and the extracted text, describe the full content of this page \
concisely but thoroughly. Focus on:
- The overall layout (single column, multi-column, slides, etc.)
- Key textual content and its structure (headings, paragraphs, lists)
- Any visual elements: figures, charts, diagrams, photos, logos
- Any tables and their key data
- Annotations, footnotes, or page furniture worth noting

Write a single paragraph suitable for use as a search-friendly text embedding."""


class DescriptionOutput(BaseModel):
    description: str = Field(description="Concise text description for embedding")


async def fetch_chunks_needing_descriptions(
    driver: AsyncDriver,
    database: str,
    document_id: str,
) -> list[dict[str, Any]]:
    """Fetch visual nodes that need text descriptions.

    Handles docling mode (image data on Chunk), pymupdf mode (image data on
    linked Image/Table nodes), and page_image mode (image + text on Page nodes).

    Returns a unified list of dicts with: chunkId, chunkType, chunkText,
    imageBase64, imageMimeType, textAsHtml, sectionContext, documentName, source.
    """
    results: list[dict[str, Any]] = []

    # Docling mode: image/table chunks have image data directly
    query_docling = """
        MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: $docId})
        WHERE c.active = true
          AND c.type IN ['image', 'table']
          AND c.imageBase64 IS NOT NULL
          AND c.textDescription IS NULL
        RETURN c.id AS chunkId, c.type AS chunkType, c.text AS chunkText,
               c.imageBase64 AS imageBase64, c.imageMimeType AS imageMimeType,
               c.textAsHtml AS textAsHtml,
               c.sectionContext AS sectionContext,
               c.documentName AS documentName,
               'docling' AS source
    """
    async with driver.session(database=database) as session:
        result = await session.run(query_docling, docId=document_id)
        for row in await result.data():
            results.append(row)

    # PyMuPDF mode: Image/Table nodes linked from Chunks via HAS_ELEMENT.
    # One row per Image/Table node (a chunk may have multiple images).
    query_pymupdf = """
        MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: $docId})
        WHERE c.active = true
        MATCH (c)-[:HAS_ELEMENT]->(e)
        WHERE e.imageBase64 IS NOT NULL AND (e:Image OR e:Table)
          AND e.textDescription IS NULL
        RETURN e.id AS chunkId,
               CASE WHEN e:Image THEN 'image' ELSE 'table' END AS chunkType,
               e.text AS chunkText,
               e.imageBase64 AS imageBase64,
               e.imageMimeType AS imageMimeType,
               e.textAsHtml AS textAsHtml,
               c.sectionContext AS sectionContext,
               coalesce(c.documentName, d.name) AS documentName,
               e.id AS elementId,
               'pymupdf' AS source
    """
    async with driver.session(database=database) as session:
        result = await session.run(query_pymupdf, docId=document_id)
        seen_element_ids: set[str] = set()
        for row in await result.data():
            eid = row.get("elementId")
            if eid and eid not in seen_element_ids:
                seen_element_ids.add(eid)
                results.append(row)

    # Page-image mode: Page nodes with rendered page image + extracted text
    query_page_image = """
        MATCH (d:Document {id: $docId})-[:HAS_PAGE]->(p:Page)
        WHERE p.imageBase64 IS NOT NULL
          AND p.textDescription IS NULL
        RETURN p.id AS chunkId, 'page' AS chunkType, p.text AS chunkText,
               p.imageBase64 AS imageBase64, p.imageMimeType AS imageMimeType,
               null AS textAsHtml,
               null AS sectionContext,
               d.name AS documentName,
               p.pageNumber AS pageNumber,
               'page_image' AS source
    """
    async with driver.session(database=database) as session:
        result = await session.run(query_page_image, docId=document_id)
        for row in await result.data():
            results.append(row)

    logger.info(
        "Chunks needing descriptions",
        document_id=document_id,
        count=len(results),
    )
    return results


async def generate_description_for_chunk(
    chunk_info: dict[str, Any],
    model: str = "gpt-5-mini",
    max_retries: int = 3,
) -> str | None:
    """Generate a text description for a single image/table chunk using VLM.

    Returns the description string, or None on failure.
    """
    chunk_type = chunk_info.get("chunkType", "image")
    image_b64 = chunk_info.get("imageBase64")
    image_mime = chunk_info.get("imageMimeType") or "image/png"
    doc_name = chunk_info.get("documentName") or "Unknown"
    sec_context = chunk_info.get("sectionContext") or ""
    text_as_html = chunk_info.get("textAsHtml") or ""
    chunk_text = chunk_info.get("chunkText") or ""

    if not image_b64:
        logger.warning("No image data for chunk", chunk_id=chunk_info.get("chunkId"))
        return None

    section_context_line = f"Section: {sec_context}\n" if sec_context else ""
    caption_line = f"Caption: {chunk_text}\n" if chunk_text else ""

    if chunk_type == "page":
        page_number = chunk_info.get("pageNumber", 0) + 1
        extracted_text = chunk_text or "(no text extracted)"
        prompt_text = PAGE_PROMPT.format(
            document_name=doc_name,
            page_number=page_number,
            extracted_text=extracted_text,
        )
    elif chunk_type == "table":
        # Prefer HTML (docling); fall back to markdown text (pymupdf)
        if text_as_html:
            table_content_section = f"Table content (HTML):\n```html\n{text_as_html}\n```"
        elif chunk_text:
            table_content_section = f"Table content:\n```\n{chunk_text}\n```"
        else:
            table_content_section = ""
        prompt_text = TABLE_PROMPT.format(
            document_name=doc_name,
            section_context_line=section_context_line,
            caption_line=caption_line,
            table_content_section=table_content_section,
        )
    else:
        prompt_text = IMAGE_PROMPT.format(
            document_name=doc_name,
            section_context_line=section_context_line,
            caption_line=caption_line,
        )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_mime};base64,{image_b64}",
                    },
                },
            ],
        }
    ]

    api_params: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": DescriptionOutput,
    }

    model_lower = model.lower()
    if "gpt-5" in model_lower:
        api_params["reasoning_effort"] = "minimal"
    elif "o1" in model_lower or "o3" in model_lower:
        pass
    else:
        api_params["temperature"] = 0.0

    for attempt in range(max_retries):
        try:
            response = await litellm.acompletion(**api_params)
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty VLM response")
            parsed = DescriptionOutput.model_validate_json(content)
            return parsed.description
        except (litellm.RateLimitError, litellm.APIError) as e:
            wait = 2**attempt
            logger.warning(
                "VLM call failed, retrying",
                chunk_id=chunk_info.get("chunkId"),
                attempt=attempt + 1,
                wait=wait,
                error=str(e),
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(wait)
            else:
                logger.error("VLM call exhausted retries", chunk_id=chunk_info.get("chunkId"))
                return None
        except Exception as e:
            logger.error(
                "VLM description generation failed",
                chunk_id=chunk_info.get("chunkId"),
                error=str(e),
            )
            return None

    return None


async def generate_descriptions_batch(
    driver: AsyncDriver,
    database: str,
    document_id: str,
    model: str = "gpt-5-mini",
    parallel: int = 5,
) -> dict[str, Any]:
    """Generate descriptions for all visual nodes in a document.

    Processes in parallel with a semaphore.
    Sets textDescription on visual nodes (text property is NOT overwritten).
    For pymupdf Image/Table nodes: adds :Chunk label, documentName, active.
    For page_image Page nodes: adds :Chunk label (documentName/active already set at creation).

    Returns stats dict.
    """
    chunks = await fetch_chunks_needing_descriptions(driver, database, document_id)
    if not chunks:
        return {
            "document_id": document_id,
            "chunks_processed": 0,
            "chunks_failed": 0,
            "message": "No chunks need descriptions.",
        }

    if not litellm.supports_vision(model):
        return {
            "document_id": document_id,
            "error": f"Model '{model}' does not support vision. Use a VLM like gpt-4.1-mini.",
        }

    semaphore = asyncio.Semaphore(parallel)
    processed = 0
    failed = 0
    description_lengths: list[int] = []

    async def process_one(chunk_info: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal processed, failed
        async with semaphore:
            description = await generate_description_for_chunk(chunk_info, model=model)
            if description:
                processed += 1
                description_lengths.append(len(description))
                return {"chunk_info": chunk_info, "description": description}
            else:
                failed += 1
                return None

    tasks = [process_one(c) for c in chunks]
    results = await asyncio.gather(*tasks)

    # Write descriptions to Neo4j
    docling_records: list[dict[str, Any]] = []
    pymupdf_records: list[dict[str, Any]] = []
    page_image_records: list[dict[str, Any]] = []

    for r in results:
        if r is None:
            continue
        chunk_info = r["chunk_info"]
        description = r["description"]
        record = {
            "id": chunk_info["chunkId"],
            "description": description,
            "documentName": chunk_info.get("documentName") or "",
        }
        source = chunk_info.get("source")
        if source == "pymupdf":
            pymupdf_records.append(record)
        elif source == "page_image":
            page_image_records.append(record)
        else:
            docling_records.append(record)

    # Docling mode: write textDescription to Chunk nodes (text stays as original)
    if docling_records:
        batch_size = 100
        for i in range(0, len(docling_records), batch_size):
            batch = docling_records[i : i + batch_size]
            async with driver.session(database=database) as session:
                await session.run(
                    """
                    UNWIND $records AS rec
                    MATCH (c:Chunk {id: rec.id})
                    SET c.textDescription = rec.description
                    """,
                    records=batch,
                )

    # PyMuPDF mode: write textDescription to Image/Table nodes, add :Chunk label + metadata
    if pymupdf_records:
        batch_size = 100
        for i in range(0, len(pymupdf_records), batch_size):
            batch = pymupdf_records[i : i + batch_size]
            async with driver.session(database=database) as session:
                await session.run(
                    """
                    UNWIND $records AS rec
                    OPTIONAL MATCH (i:Image {id: rec.id})
                    OPTIONAL MATCH (t:Table {id: rec.id})
                    WITH rec, coalesce(i, t) AS node
                    WHERE node IS NOT NULL
                    SET node:Chunk,
                        node.textDescription = rec.description,
                        node.documentName = rec.documentName,
                        node.active = true
                    """,
                    records=batch,
                )
        logger.info(
            "Descriptions written to pymupdf Image/Table nodes with :Chunk label",
            count=len(pymupdf_records),
        )

    # Page-image mode: write textDescription to Page nodes, add :Chunk label
    # (documentName and active are already set at Page creation time)
    if page_image_records:
        batch_size = 100
        for i in range(0, len(page_image_records), batch_size):
            batch = page_image_records[i : i + batch_size]
            async with driver.session(database=database) as session:
                await session.run(
                    """
                    UNWIND $records AS rec
                    MATCH (p:Page {id: rec.id})
                    SET p:Chunk,
                        p.textDescription = rec.description
                    """,
                    records=batch,
                )
        logger.info(
            "Descriptions written to Page nodes with :Chunk label",
            count=len(page_image_records),
        )

    avg_len = round(sum(description_lengths) / len(description_lengths), 1) if description_lengths else 0

    return {
        "document_id": document_id,
        "model": model,
        "chunks_processed": processed,
        "chunks_failed": failed,
        "avg_description_length": avg_len,
        "message": f"Generated {processed} descriptions ({failed} failed).",
    }
