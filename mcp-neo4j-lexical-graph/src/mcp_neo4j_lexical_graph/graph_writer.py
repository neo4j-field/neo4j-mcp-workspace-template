"""Write a ParsedDocument to Neo4j as an expanded lexical graph.

Handles:
- Document versioning (sourceId, version, active)
- Page / Element / Section / TOCEntry node creation
- All relationships (HAS_PAGE, NEXT_PAGE, HAS_ELEMENT, NEXT_ELEMENT,
  HAS_SECTION, HAS_SUBSECTION, NEXT_SECTION, CAPTION_OF, etc.)
- Constraint creation (idempotent)
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from neo4j import AsyncDriver

from .models import ParsedDocument

logger = structlog.get_logger()

# Batch size for UNWIND operations
BATCH_SIZE = 200


async def ensure_constraints(driver: AsyncDriver, database: str) -> None:
    """Create uniqueness constraints (idempotent)."""
    constraints = [
        "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
        "CREATE CONSTRAINT page_id IF NOT EXISTS FOR (p:Page) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT element_id IF NOT EXISTS FOR (e:Element) REQUIRE e.id IS UNIQUE",
        "CREATE CONSTRAINT image_id IF NOT EXISTS FOR (i:Image) REQUIRE i.id IS UNIQUE",
        "CREATE CONSTRAINT table_id IF NOT EXISTS FOR (t:Table) REQUIRE t.id IS UNIQUE",
        "CREATE CONSTRAINT section_id IF NOT EXISTS FOR (s:Section) REQUIRE s.id IS UNIQUE",
        "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
    ]
    async with driver.session(database=database) as session:
        for stmt in constraints:
            await session.run(stmt)
    logger.debug("Constraints ensured")


async def get_existing_versions(
    driver: AsyncDriver, database: str, source_id: str
) -> list[dict[str, Any]]:
    """Return existing document versions for a sourceId."""
    query = """
        MATCH (d:Document {sourceId: $sourceId})
        RETURN d.id AS id, d.version AS version, d.active AS active,
               d.parseMode AS parseMode
        ORDER BY d.version
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, sourceId=source_id)
        return await result.data()


async def deactivate_versions(
    driver: AsyncDriver, database: str, source_id: str
) -> int:
    """Set active=false on all versions for a sourceId. Returns count."""
    query = """
        MATCH (d:Document {sourceId: $sourceId})
        WHERE d.active = true
        SET d.active = false
        RETURN count(d) AS cnt
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, sourceId=source_id)
        record = await result.single()
        return record["cnt"] if record else 0


async def write_parsed_document(
    driver: AsyncDriver,
    database: str,
    doc: ParsedDocument,
) -> dict[str, Any]:
    """Write a full ParsedDocument to Neo4j.

    Returns a summary dict with counts.
    """
    await ensure_constraints(driver, database)

    # --- Document node ---
    doc_props: dict[str, Any] = {
        "id": doc.id,
        "sourceId": doc.source_id,
        "version": doc.version,
        "active": True,
        "name": doc.name,
        "source": doc.source,
        "parseMode": doc.parse_mode,
        "parseParams": json.dumps(doc.parse_params),
        "totalPages": len(doc.pages),
        "totalElements": len(doc.elements),
        "totalSections": len(doc.sections),
        "createdAt": doc.created_at,
    }
    # Merge user metadata into document properties
    for k, v in doc.metadata.items():
        safe_key = k.replace(" ", "_").replace("-", "_")
        doc_props[safe_key] = v

    async with driver.session(database=database) as session:
        await session.run(
            """
            CREATE (d:Document)
            SET d = $props
            """,
            props=doc_props,
        )
    logger.info("Document node created", doc_id=doc.id)

    # --- Page nodes ---
    page_records = []
    for p in doc.pages:
        rec: dict[str, Any] = {
            "id": f"{doc.id}_page_{p.page_number}",
            "pageNumber": p.page_number,
            "documentId": doc.id,
            "documentName": doc.name,
            "active": True,
        }
        if p.width is not None:
            rec["width"] = p.width
        if p.height is not None:
            rec["height"] = p.height
        if p.text is not None:
            rec["text"] = p.text
        if p.image_base64 is not None:
            rec["imageBase64"] = p.image_base64
            rec["imageMimeType"] = p.image_mime_type or "image/png"
        page_records.append(rec)

    await _batch_write(
        driver,
        database,
        """
        UNWIND $records AS rec
        CREATE (p:Page)
        SET p = apoc.map.removeKeys(rec, ['documentId'])
        WITH p, rec
        MATCH (d:Document {id: rec.documentId})
        CREATE (d)-[:HAS_PAGE]->(p)
        """,
        page_records,
    )

    # NEXT_PAGE chain
    if len(doc.pages) > 1:
        async with driver.session(database=database) as session:
            await session.run(
                """
                MATCH (d:Document {id: $docId})-[:HAS_PAGE]->(p:Page)
                WITH p ORDER BY p.pageNumber
                WITH collect(p) AS pages
                UNWIND range(0, size(pages)-2) AS i
                WITH pages[i] AS cur, pages[i+1] AS nxt
                CREATE (cur)-[:NEXT_PAGE]->(nxt)
                """,
                docId=doc.id,
            )

    # --- Element nodes ---
    elem_records = []
    for e in doc.elements:
        rec: dict[str, Any] = {
            "id": e.id,
            "type": e.type,
            "pageNumber": e.page_number,
            "pageId": f"{doc.id}_page_{e.page_number}",
        }
        if e.text is not None:
            rec["text"] = e.text
        if e.text_as_html is not None:
            rec["textAsHtml"] = e.text_as_html
        if e.image_base64 is not None:
            rec["imageBase64"] = e.image_base64
            rec["imageMimeType"] = e.image_mime_type or "image/png"
        if e.coordinates is not None:
            rec["coordinates"] = json.dumps(e.coordinates)
        if e.level is not None:
            rec["level"] = e.level
        elem_records.append(rec)

    await _batch_write(
        driver,
        database,
        """
        UNWIND $records AS rec
        CREATE (e:Element)
        SET e = apoc.map.removeKeys(rec, ['pageId'])
        WITH e, rec
        MATCH (p:Page {id: rec.pageId})
        CREATE (p)-[:HAS_ELEMENT]->(e)
        """,
        elem_records,
    )

    # NEXT_ELEMENT chains (per page, preserving reading order)
    for p in doc.pages:
        if len(p.element_ids) > 1:
            async with driver.session(database=database) as session:
                await session.run(
                    """
                    UNWIND $elementIds AS eid
                    MATCH (e:Element {id: eid})
                    WITH collect(e) AS elems
                    UNWIND range(0, size(elems)-2) AS i
                    WITH elems[i] AS cur, elems[i+1] AS nxt
                    CREATE (cur)-[:NEXT_ELEMENT]->(nxt)
                    """,
                    elementIds=p.element_ids,
                )

    # CAPTION_OF relationships
    caption_pairs = [
        {"captionId": e.id, "targetId": e.caption_target_id}
        for e in doc.elements
        if e.caption_target_id is not None
    ]
    if caption_pairs:
        await _batch_write(
            driver,
            database,
            """
            UNWIND $records AS rec
            MATCH (cap:Element {id: rec.captionId})
            MATCH (tgt:Element {id: rec.targetId})
            CREATE (cap)-[:CAPTION_OF]->(tgt)
            """,
            caption_pairs,
        )

    # --- Section nodes + hierarchy ---
    if doc.sections:
        sec_records = [
            {
                "id": s.id,
                "title": s.title,
                "level": s.level,
                "documentId": doc.id,
            }
            for s in doc.sections
        ]
        await _batch_write(
            driver,
            database,
            """
            UNWIND $records AS rec
            CREATE (s:Section)
            SET s.id = rec.id, s.title = rec.title, s.level = rec.level
            WITH s, rec
            MATCH (d:Document {id: rec.documentId})
            CREATE (d)-[:HAS_SECTION]->(s)
            """,
            sec_records,
        )

        # HAS_SUBSECTION relationships
        sub_pairs: list[dict[str, str]] = []
        for s in doc.sections:
            for child_id in s.subsection_ids:
                sub_pairs.append({"parentId": s.id, "childId": child_id})
        if sub_pairs:
            await _batch_write(
                driver,
                database,
                """
                UNWIND $records AS rec
                MATCH (parent:Section {id: rec.parentId})
                MATCH (child:Section {id: rec.childId})
                CREATE (parent)-[:HAS_SUBSECTION]->(child)
                """,
                sub_pairs,
            )

        # NEXT_SECTION chain (flat order among same-level siblings under same parent)
        # We build from the document's section list ordering
        top_level_ids = [
            s.id
            for s in doc.sections
            if not any(s.id in p.subsection_ids for p in doc.sections)
        ]
        await _create_next_chain(driver, database, "Section", top_level_ids, "NEXT_SECTION")

        # Also chain subsections within each parent
        for s in doc.sections:
            if len(s.subsection_ids) > 1:
                await _create_next_chain(
                    driver, database, "Section", s.subsection_ids, "NEXT_SECTION"
                )

        # HAS_ELEMENT from Sections
        sec_elem_pairs: list[dict[str, str]] = []
        for s in doc.sections:
            for eid in s.element_ids:
                sec_elem_pairs.append({"sectionId": s.id, "elementId": eid})
        if sec_elem_pairs:
            await _batch_write(
                driver,
                database,
                """
                UNWIND $records AS rec
                MATCH (s:Section {id: rec.sectionId})
                MATCH (e:Element {id: rec.elementId})
                CREATE (s)-[:HAS_ELEMENT]->(e)
                """,
                sec_elem_pairs,
            )

    summary = {
        "document_id": doc.id,
        "source_id": doc.source_id,
        "version": doc.version,
        "pages": len(doc.pages),
        "elements": len(doc.elements),
        "sections": len(doc.sections),
        "captions_linked": len(caption_pairs) if caption_pairs else 0,
    }
    logger.info("Graph written", **summary)
    return summary


# ---- helpers ----


async def _batch_write(
    driver: AsyncDriver,
    database: str,
    query: str,
    records: list[dict[str, Any]],
) -> None:
    """Execute an UNWIND query in batches."""
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        async with driver.session(database=database) as session:
            await session.run(query, records=batch)


async def _create_next_chain(
    driver: AsyncDriver,
    database: str,
    label: str,
    ordered_ids: list[str],
    rel_type: str,
) -> None:
    """Create a NEXT-style chain among nodes identified by their ids."""
    if len(ordered_ids) < 2:
        return
    pairs = [
        {"fromId": ordered_ids[i], "toId": ordered_ids[i + 1]}
        for i in range(len(ordered_ids) - 1)
    ]
    query = f"""
        UNWIND $pairs AS pair
        MATCH (a:{label} {{id: pair.fromId}})
        MATCH (b:{label} {{id: pair.toId}})
        CREATE (a)-[:{rel_type}]->(b)
    """
    async with driver.session(database=database) as session:
        await session.run(query, pairs=pairs)
