"""Write a ParsedDocument to Neo4j as an expanded lexical graph.

Handles:
- Document versioning (sourceId, version, active)
- Page / Element / Section node creation
- All relationships (HAS_PAGE, NEXT_PAGE, HAS_ELEMENT, NEXT_ELEMENT,
  HAS_SECTION, HAS_SUBSECTION, NEXT_SECTION, CAPTION_OF, etc.)
- Constraint creation (idempotent)
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import structlog
from neo4j import AsyncDriver

from .models import ParsedDocument
from .metadata import normalize_document_metadata

logger = structlog.get_logger()

# Batch size for UNWIND operations
BATCH_SIZE = 200


async def ensure_constraints(
    driver: AsyncDriver,
    database: str,
    parse_mode: str,
    extract_images: bool = False,
    extract_tables: bool = False,
) -> None:
    """Create uniqueness constraints only for node types that will actually be written.

    Avoids phantom labels appearing in the Neo4j browser for node types
    that don't exist in the graph (e.g. Page constraint in pymupdf mode,
    Section constraint when no sections are extracted).
    """
    # Always needed: every parse mode produces Document, Element, and Chunk nodes
    constraints = [
        "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
        "CREATE CONSTRAINT element_id IF NOT EXISTS FOR (e:Element) REQUIRE e.id IS UNIQUE",
        "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
    ]
    # Page nodes: only page_image mode create them
    if parse_mode == "page_image":
        constraints.append(
            "CREATE CONSTRAINT page_id IF NOT EXISTS FOR (p:Page) REQUIRE p.id IS UNIQUE"
        )
    # Section nodes: only docling/document modes extract sections
    if parse_mode in ("docling", "document"):
        constraints.append(
            "CREATE CONSTRAINT section_id IF NOT EXISTS FOR (s:Section) REQUIRE s.id IS UNIQUE"
        )
    # Image and Table nodes: only when explicitly requested in pymupdf mode
    if extract_images:
        constraints.append(
            "CREATE CONSTRAINT image_id IF NOT EXISTS FOR (i:Image) REQUIRE i.id IS UNIQUE"
        )
    if extract_tables:
        constraints.append(
            "CREATE CONSTRAINT table_id IF NOT EXISTS FOR (t:Table) REQUIRE t.id IS UNIQUE"
        )
    async with driver.session(database=database) as session:
        for stmt in constraints:
            await (await session.run(stmt)).consume()
    logger.debug(
        "Constraints ensured", parse_mode=parse_mode, constraints=len(constraints)
    )


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


async def write_parsed_document(
    driver: AsyncDriver,
    database: str,
    doc: ParsedDocument,
) -> dict[str, Any]:
    """Write a full ParsedDocument to Neo4j.

    Returns a summary dict with counts.
    """
    # Validate and create schema before opening the data transaction: Neo4j does
    # not allow schema and data updates in the same transaction.
    normalize_document_metadata(doc.metadata)
    await ensure_constraints(
        driver,
        database,
        parse_mode=doc.parse_mode,
        extract_images=doc.parse_params.get("extract_images", False),
        extract_tables=doc.parse_params.get("extract_tables", False),
    )
    return await write_document_atomically(
        driver, database, doc.source_id, doc.id,
        lambda transaction_driver: _write_parsed_document(transaction_driver, database, doc),
    )


async def _write_parsed_document(
    driver: AsyncDriver, database: str, doc: ParsedDocument,
) -> dict[str, Any]:
    """Write graph records using the caller's single data transaction."""
    metadata = normalize_document_metadata(doc.metadata)
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
    if doc.source_format is not None:
        doc_props["sourceFormat"] = doc.source_format
    doc_props.update(metadata)

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
        SET p = rec
        REMOVE p.documentId
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
    for order, e in enumerate(doc.elements):
        rec: dict[str, Any] = {
            "id": e.id,
            "type": e.type,
            "pageNumber": e.page_number,
            "order": order,
        }
        if e.page_number is not None:
            rec["pageId"] = f"{doc.id}_page_{e.page_number}"
        if not doc.pages:
            rec["documentId"] = doc.id
        if e.source_anchor is not None:
            rec["sourceAnchor"] = e.source_anchor
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
        if e.font_size_max is not None:
            rec["fontSizeMax"] = e.font_size_max
        elem_records.append(rec)

    if doc.pages:
        element_membership = """
            MATCH (p:Page {id: rec.pageId})
            CREATE (p)-[:HAS_ELEMENT]->(e)
        """
    else:
        element_membership = """
            MATCH (d:Document {id: rec.documentId})
            CREATE (d)-[:HAS_ELEMENT]->(e)
        """
    await _batch_write(
        driver,
        database,
        """
        UNWIND $records AS rec
        CREATE (e:Element)
        SET e = rec
        REMOVE e.pageId, e.documentId
        WITH e, rec
        """
        + element_membership,
        elem_records,
    )
    if not doc.pages:
        await _create_next_chain(
            driver,
            database,
            "Element",
            [element.id for element in doc.elements],
            "NEXT_ELEMENT",
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
        # Materialize navigation metadata once so outline reads need no content scan.
        # Page numbers use the same zero-based convention as Elements and Pages.
        element_pages = {e.id: e.page_number for e in doc.elements}
        sections_by_id = {section.id: section for section in doc.sections}
        sec_records = []
        for order, section in enumerate(doc.sections):
            pending = [section.id]
            visited = set()
            pages = set()
            while pending:
                section_id = pending.pop()
                if section_id in visited:
                    continue
                visited.add(section_id)
                child = sections_by_id.get(section_id)
                if child is None:
                    continue
                pages.update(
                    element_pages[eid]
                    for eid in child.element_ids
                    if element_pages.get(eid) is not None
                )
                pending.extend(child.subsection_ids)
            sec_records.append(
                {
                    "id": section.id,
                    "title": section.title,
                    "level": section.level,
                    "order": order,
                    "pageStart": min(pages) if pages else None,
                    "pageEnd": max(pages) if pages else None,
                    "documentId": doc.id,
                }
            )
        await _batch_write(
            driver,
            database,
            """
            UNWIND $records AS rec
            CREATE (s:Section)
            SET s.id = rec.id, s.title = rec.title, s.level = rec.level,
                s.order = rec.order, s.pageStart = rec.pageStart, s.pageEnd = rec.pageEnd
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
        await _create_next_chain(
            driver, database, "Section", top_level_ids, "NEXT_SECTION"
        )

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
        "sourcePageCount": len(doc.pages),
        "pageNodeCount": len(doc.pages),
        "elements": len(doc.elements),
        "sections": len(doc.sections),
        "captions_linked": len(caption_pairs) if caption_pairs else 0,
    }
    logger.info("Graph written", **summary)
    return summary


class _TransactionSession:
    """Let existing batched graph writers share one explicit transaction."""

    def __init__(self, transaction):
        self.transaction = transaction

    async def __aenter__(self):
        return self.transaction

    async def __aexit__(self, *_):
        return False


class _TransactionDriver:
    def __init__(self, transaction):
        self.transaction = transaction

    def session(self, **_):
        return _TransactionSession(self.transaction)


async def write_document_atomically(
    driver: AsyncDriver,
    database: str,
    source_id: str,
    document_id: str,
    write: Callable[[Any], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Publish a complete graph and switch its active version in one commit.

    Queries remain batched, but no graph records or active-version changes become
    visible until all writes succeed. A cancelled/failed transaction rolls back.
    """
    async def operation(transaction):
        summary = await write(_TransactionDriver(transaction))
        await _activate_document(transaction, source_id, document_id)
        return summary

    async with driver.session(database=database) as session:
        return await session.execute_write(operation)


async def _activate_document(transaction, source_id: str, document_id: str) -> None:
    result = await transaction.run(
        """
        MATCH (d:Document)
        WHERE d.id = $documentId OR d.sourceId = $sourceId
        SET d.active = (d.id = $documentId)
        """,
        sourceId=source_id, documentId=document_id,
    )
    await result.consume()


async def activate_document_version(
    driver: AsyncDriver, database: str, document_id: str,
    chunk_set_version: int | None = None,
) -> int | None:
    """Switch an existing document/chunk set together, or leave both unchanged."""
    async def operation(transaction):
        result = await transaction.run(
            "MATCH (d:Document {id: $id}) RETURN d.sourceId AS sourceId",
            id=document_id,
        )
        record = await result.single()
        if record is None:
            raise ValueError(f"Document not found: {document_id}")
        count = None
        if chunk_set_version is not None:
            result = await transaction.run(
                """
                MATCH (c:Chunk)-[:PART_OF]->(:Document {id: $id})
                WHERE c.chunkSetVersion = $version
                RETURN count(c) AS count
                """,
                id=document_id, version=chunk_set_version,
            )
            count = (await result.single())["count"]
            if not count:
                raise ValueError(
                    f"Chunk set v{chunk_set_version} not found for {document_id}; "
                    "active versions were preserved."
                )
        await _activate_document(transaction, record["sourceId"], document_id)
        if chunk_set_version is not None:
            result = await transaction.run(
                """
                MATCH (c:Chunk)-[:PART_OF]->(:Document {id: $id})
                SET c.active = coalesce(c.chunkSetVersion = $version, false)
                """,
                id=document_id, version=chunk_set_version,
            )
            await result.consume()
        return count

    async with driver.session(database=database) as session:
        return await session.execute_write(operation)


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
