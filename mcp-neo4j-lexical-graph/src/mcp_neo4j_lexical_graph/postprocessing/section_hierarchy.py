"""Post-processing: assign section hierarchy levels using LLM or agent.

Fixes Docling's flat level=1 sections by assigning appropriate heading
levels based on section titles. Two modes:
  - LLM mode (default): asks gpt-5-mini (medium reasoning) to infer levels.
  - Agent mode: the calling agent provides explicit levels, skipping the LLM.

After assignment, rebuilds HAS_SUBSECTION relationships and propagates
full heading chains to active Chunk nodes as sectionContext.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import litellm
import structlog
from neo4j import AsyncDriver
from pydantic import BaseModel, Field

from ..graph_reader import (
    get_active_chunks_for_document,
    get_element_section_map,
    get_sections_for_document,
)

logger = structlog.get_logger()

SYSTEM_PROMPT = """\
You are a document structure analyst. Given a list of section titles extracted \
from a document (in reading order), assign each one a heading level \
(1 = top-level, 2 = sub-section, 3 = sub-sub-section, etc.).

Rules:
- Use only levels 1 through 5.
- Determine hierarchy from structural cues in the titles:
  - Named structural units indicate nesting: CHAPTER > Section > Article > Paragraph
  - Numbered prefixes show level when combined with a parent: \
"1. Field of Invention" under "BACKGROUND" means level 2.
  - In scientific papers, single-number prefixes like "1 |", "2 |", "3 |" \
typically denote top-level sections (level 1), with "1.1", "2.3" as sub-sections (level 2).
  - ALL-CAPS headings often indicate major structural divisions.
- Use the surrounding context to determine each section's level. \
A section that appears between two level-2 sections is likely also level 2. \
A section that appears right after a known parent is likely a child.
- Standard academic back-matter (Abstract, References, Appendix, Keywords, \
Acknowledgements, Conflict of Interest, ORCID, Supporting Information, etc.) \
is typically level 1.
- Sidebar or callout sections that interrupt the main flow should match the \
level of the surrounding context (usually level 1).
- Document metadata (titles, dates, reference numbers, subject lines, TOC) \
are level 1 and do NOT create nesting.
- Return a JSON array with one object per section, preserving the input order.
"""


class SectionLevel(BaseModel):
    index: int = Field(description="0-based index of the section in the input list")
    level: int = Field(description="Heading level: 1 = top, 2 = sub-section, etc.")


class HierarchyOutput(BaseModel):
    sections: list[SectionLevel]


async def infer_hierarchy_from_llm(
    sections: list[dict[str, Any]],
    document_name: str,
    model: str = "gpt-5-mini",
    max_retries: int = 3,
) -> dict[str, int]:
    """Ask LLM to assign heading levels to section titles.

    Returns {section_id: level}.
    """
    if not sections:
        return {}

    titles_for_llm = "\n".join(
        f"{i}. {s.get('title', '(untitled)')}" for i, s in enumerate(sections)
    )
    user_msg = (
        f"Document: {document_name}\n\n"
        f"Section titles (in reading order):\n{titles_for_llm}\n\n"
        f"Assign heading levels to each section."
    )

    api_params: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "response_format": HierarchyOutput,
    }

    model_lower = model.lower()
    if "gpt-5" in model_lower:
        api_params["reasoning_effort"] = "medium"
    elif "o1" in model_lower or "o3" in model_lower:
        pass
    else:
        api_params["temperature"] = 0.0
    logger.info("LLM hierarchy call", model=model, reasoning="medium" if "gpt-5" in model_lower else "default", sections=len(sections))

    for attempt in range(max_retries):
        try:
            response = await litellm.acompletion(**api_params)
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty LLM response")
            parsed = HierarchyOutput.model_validate_json(content)
            return {
                sections[sl.index]["id"]: sl.level
                for sl in parsed.sections
                if sl.index < len(sections)
            }
        except (litellm.RateLimitError, litellm.APIError) as e:
            wait = 2**attempt
            logger.warning("LLM call failed, retrying", attempt=attempt + 1, wait=wait, error=str(e))
            if attempt < max_retries - 1:
                await asyncio.sleep(wait)
            else:
                raise
        except Exception as e:
            logger.error("LLM hierarchy inference failed", error=str(e))
            raise

    return {}


async def update_section_levels(
    driver: AsyncDriver,
    database: str,
    level_map: dict[str, int],
) -> int:
    """SET level on Section nodes. Returns count of updated sections."""
    if not level_map:
        return 0

    records = [{"id": sid, "level": lvl} for sid, lvl in level_map.items()]
    query = """
        UNWIND $records AS rec
        MATCH (s:Section {id: rec.id})
        SET s.level = rec.level
        RETURN count(s) AS cnt
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, records=records)
        rec = await result.single()
        return rec["cnt"] if rec else 0


async def rebuild_subsection_relationships(
    driver: AsyncDriver,
    database: str,
    document_id: str,
) -> int:
    """Delete old HAS_SUBSECTION and rebuild from section levels.

    Parent = nearest preceding section with a strictly lower level.
    Returns count of HAS_SUBSECTION relationships created.
    """
    # Delete existing HAS_SUBSECTION
    async with driver.session(database=database) as session:
        await session.run(
            """
            MATCH (d:Document {id: $docId})-[:HAS_SECTION*]->(s:Section)
            OPTIONAL MATCH (s)-[r:HAS_SUBSECTION]->()
            DELETE r
            """,
            docId=document_id,
        )

    # Get sections in order
    sections = await get_sections_for_document(driver, database, document_id)
    if not sections:
        return 0

    # Determine parent for each section (nearest preceding with lower level)
    parent_pairs: list[dict[str, str]] = []
    for i, sec in enumerate(sections):
        level = sec.get("level", 1) or 1
        for j in range(i - 1, -1, -1):
            prev_level = sections[j].get("level", 1) or 1
            if prev_level < level:
                parent_pairs.append({
                    "parentId": sections[j]["id"],
                    "childId": sec["id"],
                })
                break

    if not parent_pairs:
        return 0

    query = """
        UNWIND $pairs AS pair
        MATCH (parent:Section {id: pair.parentId})
        MATCH (child:Section {id: pair.childId})
        CREATE (parent)-[:HAS_SUBSECTION]->(child)
        RETURN count(*) AS cnt
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, pairs=parent_pairs)
        rec = await result.single()
        return rec["cnt"] if rec else 0


async def build_heading_chains(
    driver: AsyncDriver,
    database: str,
    document_id: str,
) -> dict[str, str]:
    """Walk parent chain per section to build full heading path.

    Returns {section_id: "Chapter 1 > Section 1.1 > Subsection 1.1.1"}.
    """
    sections = await get_sections_for_document(driver, database, document_id)
    if not sections:
        return {}

    # Build parent map from HAS_SUBSECTION
    query = """
        MATCH (d:Document {id: $docId})-[:HAS_SECTION*]->(s:Section)
        OPTIONAL MATCH (parent:Section)-[:HAS_SUBSECTION]->(s)
        RETURN s.id AS id, s.title AS title, parent.id AS parentId
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, docId=document_id)
        rows = await result.data()

    sec_title: dict[str, str] = {}
    sec_parent: dict[str, str | None] = {}
    for row in rows:
        sec_title[row["id"]] = row.get("title") or "(untitled)"
        sec_parent[row["id"]] = row.get("parentId")

    chains: dict[str, str] = {}
    for sid in sec_title:
        parts: list[str] = []
        current: str | None = sid
        while current:
            parts.append(sec_title.get(current, ""))
            current = sec_parent.get(current)
        parts.reverse()
        chains[sid] = " > ".join(parts)

    return chains


async def propagate_context_to_chunks(
    driver: AsyncDriver,
    database: str,
    document_id: str,
    heading_chains: dict[str, str],
) -> int:
    """Update sectionContext on active Chunk nodes using heading chains.

    For text chunks: use the heading chain of the chunk's section.
    For image/table chunks with captions: keep existing sectionContext.
    Returns count of updated chunks.
    """
    # Get element -> section map
    elem_to_section = await get_element_section_map(driver, database, document_id)

    # Get active chunks
    chunks = await get_active_chunks_for_document(driver, database, document_id)
    if not chunks:
        return 0

    # Get chunk -> element IDs (first element determines section)
    query = """
        MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: $docId})
        WHERE c.active = true
        OPTIONAL MATCH (c)-[:HAS_ELEMENT]->(e)
        WITH c.id AS chunkId, collect(e.id) AS elementIds
        RETURN chunkId, elementIds
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, docId=document_id)
        rows = await result.data()

    chunk_elements: dict[str, list[str]] = {
        r["chunkId"]: r["elementIds"] for r in rows
    }

    # Build updates: {chunk_id: new_section_context}
    updates: list[dict[str, str]] = []
    for chunk in chunks:
        chunk_id = chunk["id"]
        ctype = chunk.get("type", "text")
        existing_context = chunk.get("sectionContext") or ""

        # Image/table chunks with existing context (caption) keep it
        if ctype in ("image", "table") and existing_context:
            continue

        # Find section via elements
        elem_ids = chunk_elements.get(chunk_id, [])
        section_id = None
        for eid in elem_ids:
            sid = elem_to_section.get(eid)
            if sid:
                section_id = sid
                break

        # Fallback: match by sectionHeading
        if not section_id:
            sec_heading = chunk.get("sectionHeading") or ""
            if sec_heading:
                for sid, chain in heading_chains.items():
                    if chain.endswith(sec_heading):
                        section_id = sid
                        break

        if section_id and section_id in heading_chains:
            new_context = heading_chains[section_id]
            if new_context != existing_context:
                updates.append({"id": chunk_id, "context": new_context})

    if not updates:
        return 0

    update_query = """
        UNWIND $records AS rec
        MATCH (c:Chunk {id: rec.id})
        SET c.sectionContext = rec.context
        RETURN count(c) AS cnt
    """
    async with driver.session(database=database) as session:
        result = await session.run(update_query, records=updates)
        rec = await result.single()
        return rec["cnt"] if rec else 0


async def assign_section_hierarchy(
    driver: AsyncDriver,
    database: str,
    document_id: str,
    document_name: str,
    model: str = "gpt-5-mini",
    hierarchy: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Full orchestration: infer or apply levels -> update -> rebuild rels -> heading chains -> propagate.

    Args:
        hierarchy: Optional agent-provided levels as [{id: "section_id", level: N}, ...].
                   When provided, the LLM call is skipped entirely.

    Returns summary dict with counts and hierarchy info.
    """
    # 1. Get current sections
    sections = await get_sections_for_document(driver, database, document_id)
    if not sections:
        return {"error": "No sections found for this document."}

    logger.info("Starting hierarchy assignment", document_id=document_id, sections=len(sections))

    # 2. Determine levels: agent-provided or LLM-inferred
    mode: str
    if hierarchy is not None:
        level_map = {item["id"]: item["level"] for item in hierarchy}
        mode = "agent"
        logger.info("Using agent-provided hierarchy", assignments=len(level_map))
    else:
        try:
            level_map = await infer_hierarchy_from_llm(sections, document_name, model=model)
            mode = "llm"
        except Exception as e:
            logger.warning("LLM call failed, returning sections for agent", error=str(e))
            section_list = [
                {"id": s["id"], "title": s.get("title", ""), "currentLevel": s.get("level", 1)}
                for s in sections
            ]
            return {
                "document_id": document_id,
                "needs_agent_input": True,
                "totalSections": len(sections),
                "sections": section_list,
                "message": (
                    "LLM call failed. Please provide hierarchy by calling this tool again "
                    "with the hierarchy parameter: [{id: 'section_id', level: N}, ...]"
                ),
            }

    if not level_map:
        return {"error": "No hierarchy assignments produced."}

    # 3. Update section levels
    updated_sections = await update_section_levels(driver, database, level_map)
    logger.info("Section levels updated", count=updated_sections)

    # 4. Rebuild HAS_SUBSECTION relationships
    subsection_count = await rebuild_subsection_relationships(driver, database, document_id)
    logger.info("HAS_SUBSECTION rebuilt", count=subsection_count)

    # 5. Build heading chains
    heading_chains = await build_heading_chains(driver, database, document_id)

    # 6. Propagate to chunks
    chunks_updated = await propagate_context_to_chunks(
        driver, database, document_id, heading_chains
    )
    logger.info("Chunk contexts updated", count=chunks_updated)

    # Build hierarchy tree for output
    hierarchy_tree: list[dict[str, Any]] = []
    for sec in sections:
        sid = sec["id"]
        hierarchy_tree.append({
            "id": sid,
            "title": sec.get("title", ""),
            "originalLevel": sec.get("level", 1),
            "assignedLevel": level_map.get(sid, sec.get("level", 1)),
            "headingChain": heading_chains.get(sid, ""),
        })

    return {
        "document_id": document_id,
        "mode": mode,
        "model": model if mode == "llm" else None,
        "totalSections": len(sections),
        "sectionsUpdated": updated_sections,
        "subsectionRelationshipsCreated": subsection_count,
        "chunksContextUpdated": chunks_updated,
        "hierarchy": hierarchy_tree,
    }
