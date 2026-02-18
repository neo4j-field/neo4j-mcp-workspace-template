"""Read lexical graph data from Neo4j.

Used by chunkers (to read Elements/Sections) and the verifier.
"""

from __future__ import annotations

from typing import Any

import structlog
from neo4j import AsyncDriver

logger = structlog.get_logger()


async def get_document(
    driver: AsyncDriver, database: str, document_id: str
) -> dict[str, Any] | None:
    """Return a single Document node as a dict, or None."""
    query = "MATCH (d:Document {id: $id}) RETURN properties(d) AS props"
    async with driver.session(database=database) as session:
        result = await session.run(query, id=document_id)
        record = await result.single()
        return record["props"] if record else None


async def list_all_documents(
    driver: AsyncDriver, database: str
) -> list[dict[str, Any]]:
    """Return all Document nodes grouped by sourceId."""
    query = """
        MATCH (d:Document)
        OPTIONAL MATCH (d)-[:HAS_PAGE]->(p:Page)
        OPTIONAL MATCH (d)-[:HAS_SECTION]->(s:Section)
        WITH d,
             count(DISTINCT p) AS pageCount,
             count(DISTINCT s) AS sectionCount
        OPTIONAL MATCH (c:Chunk)-[:PART_OF]->(d)
        WITH d, pageCount, sectionCount,
             count(DISTINCT c) AS totalChunkCount,
             collect(DISTINCT {
                 chunkSetVersion: c.chunkSetVersion,
                 active: c.active,
                 strategy: c.strategy
             }) AS chunkSets
        OPTIONAL MATCH (d)<-[:PART_OF]-(ce:Chunk)
        WHERE ce.text_embedding IS NOT NULL
        WITH d, pageCount, sectionCount, totalChunkCount, chunkSets,
             count(ce) AS embeddedCount
        RETURN d.id AS id,
               d.sourceId AS sourceId,
               d.version AS version,
               d.active AS active,
               d.name AS name,
               d.source AS source,
               d.parseMode AS parseMode,
               d.totalElements AS elementCount,
               pageCount,
               sectionCount,
               totalChunkCount,
               embeddedCount > 0 AS hasEmbeddings,
               d.createdAt AS createdAt
        ORDER BY d.sourceId, d.version
    """
    async with driver.session(database=database) as session:
        result = await session.run(query)
        return await result.data()


async def get_elements_for_document(
    driver: AsyncDriver, database: str, document_id: str
) -> list[dict[str, Any]]:
    """Return all Elements for a document in reading order by walking NEXT_ELEMENT chain.

    Fetches all elements with their next pointers, then walks the linked list
    in Python to produce the correct reading order.
    """
    query = """
        MATCH (d:Document {id: $docId})-[:HAS_PAGE]->(p:Page)-[:HAS_ELEMENT]->(e:Element)
        OPTIONAL MATCH (e)-[:NEXT_ELEMENT]->(nxt:Element)
        RETURN e.id AS id, e.type AS type, e.text AS text,
               e.textAsHtml AS textAsHtml,
               e.imageBase64 AS imageBase64,
               e.imageMimeType AS imageMimeType,
               e.pageNumber AS pageNumber,
               e.level AS level,
               nxt.id AS nextId
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, docId=document_id)
        rows = await result.data()

    if not rows:
        return []

    # Build lookup: id -> row, and set of all ids that are a "next" target
    by_id: dict[str, dict[str, Any]] = {}
    has_prev: set[str] = set()
    for row in rows:
        by_id[row["id"]] = row
        if row.get("nextId"):
            has_prev.add(row["nextId"])

    # Find chain head(s): elements with no incoming NEXT_ELEMENT
    heads = [rid for rid in by_id if rid not in has_prev]

    # Walk chain(s) starting from heads
    ordered: list[dict[str, Any]] = []
    visited: set[str] = set()
    for head in sorted(heads):
        current = head
        while current and current not in visited:
            visited.add(current)
            row = by_id.get(current)
            if row:
                ordered.append({
                    k: v for k, v in row.items() if k != "nextId"
                })
                current = row.get("nextId")
            else:
                break

    # Append any elements not reached by chain walking (orphans)
    for rid, row in by_id.items():
        if rid not in visited:
            ordered.append({
                k: v for k, v in row.items() if k != "nextId"
            })

    return ordered


async def get_sections_for_document(
    driver: AsyncDriver, database: str, document_id: str
) -> list[dict[str, Any]]:
    """Return all Sections and their element IDs for a document, in creation order."""
    query = """
        MATCH (d:Document {id: $docId})-[:HAS_SECTION*]->(s:Section)
        OPTIONAL MATCH (s)-[:HAS_ELEMENT]->(e:Element)
        WITH s, collect(e.id) AS elementIds
        RETURN s.id AS id, s.title AS title, s.level AS level, elementIds
        ORDER BY toInteger(split(s.id, '_sec_')[-1])
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, docId=document_id)
        return await result.data()


async def get_pages_for_document(
    driver: AsyncDriver, database: str, document_id: str
) -> list[dict[str, Any]]:
    """Return all Pages with their element IDs in reading order."""
    query = """
        MATCH (d:Document {id: $docId})-[:HAS_PAGE]->(p:Page)
        OPTIONAL MATCH (p)-[:HAS_ELEMENT]->(e:Element)
        WITH p, collect(e.id) AS elementIds
        RETURN p.id AS id, p.pageNumber AS pageNumber, p.text AS text,
               elementIds
        ORDER BY p.pageNumber
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, docId=document_id)
        return await result.data()


async def get_existing_chunk_set_versions(
    driver: AsyncDriver, database: str, document_id: str
) -> list[dict[str, Any]]:
    """Return distinct chunk set versions for a document."""
    query = """
        MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: $docId})
        WITH DISTINCT c.chunkSetVersion AS ver, c.active AS active,
             c.strategy AS strategy, c.strategyParams AS params
        RETURN ver, active, strategy, params
        ORDER BY ver
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, docId=document_id)
        return await result.data()


async def delete_chunks_for_document(
    driver: AsyncDriver, database: str, document_id: str, *, only_inactive: bool = False
) -> int:
    """Delete chunk nodes (and their relationships) for a document.

    If only_inactive=True, only deletes chunks where active=false.
    Returns count of deleted chunks.
    """
    where = "WHERE c.active = false" if only_inactive else ""
    query = f"""
        MATCH (c:Chunk)-[:PART_OF]->(d:Document {{id: $docId}})
        {where}
        WITH c LIMIT 10000
        DETACH DELETE c
        RETURN count(*) AS cnt
    """
    total = 0
    async with driver.session(database=database) as session:
        while True:
            result = await session.run(query, docId=document_id)
            record = await result.single()
            batch_cnt = record["cnt"] if record else 0
            total += batch_cnt
            if batch_cnt < 10000:
                break
    return total


async def deactivate_chunks_for_document(
    driver: AsyncDriver, database: str, document_id: str
) -> int:
    """Set active=false on all chunks for a document. Returns count."""
    query = """
        MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: $docId})
        WHERE c.active = true
        SET c.active = false
        RETURN count(c) AS cnt
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, docId=document_id)
        record = await result.single()
        return record["cnt"] if record else 0


async def get_section_hierarchy(
    driver: AsyncDriver, database: str, document_id: str
) -> list[dict[str, Any]]:
    """Return sections with HAS_SUBSECTION parent info for hierarchy reconstruction.

    Returns list of dicts: {id, title, level, parentId (via HAS_SUBSECTION or null)}.
    """
    query = """
        MATCH (d:Document {id: $docId})-[:HAS_SECTION*]->(s:Section)
        OPTIONAL MATCH (parent:Section)-[:HAS_SUBSECTION]->(s)
        RETURN s.id AS id, s.title AS title, s.level AS level,
               parent.id AS parentId
        ORDER BY toInteger(split(s.id, '_sec_')[-1])
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, docId=document_id)
        return await result.data()


async def get_element_section_map(
    driver: AsyncDriver, database: str, document_id: str
) -> dict[str, str]:
    """Return {element_id: section_id} for all elements belonging to sections."""
    query = """
        MATCH (d:Document {id: $docId})-[:HAS_SECTION*]->(s:Section)-[:HAS_ELEMENT]->(e:Element)
        RETURN e.id AS elementId, s.id AS sectionId
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, docId=document_id)
        rows = await result.data()
    return {r["elementId"]: r["sectionId"] for r in rows}


async def get_active_chunks_for_document(
    driver: AsyncDriver, database: str, document_id: str,
    *, types: list[str] | None = None
) -> list[dict[str, Any]]:
    """Return active chunks for a document, optionally filtered by type.

    Args:
        types: If provided, only return chunks with these types (e.g., ["image", "table"]).
    """
    type_filter = ""
    params: dict[str, Any] = {"docId": document_id}
    if types:
        type_filter = "AND c.type IN $types"
        params["types"] = types

    query = f"""
        MATCH (c:Chunk)-[:PART_OF]->(d:Document {{id: $docId}})
        WHERE c.active = true {type_filter}
        RETURN c.id AS id, c.type AS type, c.text AS text,
               c.tokenCount AS tokenCount, c.index AS idx,
               c.sectionHeading AS sectionHeading,
               c.sectionContext AS sectionContext,
               c.documentName AS documentName,
               c.imageBase64 AS imageBase64,
               c.imageMimeType AS imageMimeType,
               c.textAsHtml AS textAsHtml,
               c.chunkSetVersion AS chunkSetVersion
        ORDER BY c.index
    """
    async with driver.session(database=database) as session:
        result = await session.run(query, **params)
        return await result.data()


async def delete_document_cascade(
    driver: AsyncDriver, database: str, document_id: str
) -> dict[str, int]:
    """Delete a document and ALL its children (pages, elements, sections, chunks, toc entries)."""
    counts: dict[str, int] = {}

    for label, match in [
        ("Chunk", "MATCH (n:Chunk)-[:PART_OF]->(d:Document {id: $docId})"),
        ("Section", "MATCH (d:Document {id: $docId})-[:HAS_SECTION*]->(n:Section)"),
        ("Element", "MATCH (n:Element) WHERE n.id STARTS WITH $docId"),
        ("Image", "MATCH (d:Document {id: $docId})-[:HAS_ELEMENT]->(n:Image)"),
        ("Table", "MATCH (d:Document {id: $docId})-[:HAS_ELEMENT]->(n:Table)"),
        ("Page", "MATCH (d:Document {id: $docId})-[:HAS_PAGE]->(n:Page)"),
        ("Document", "MATCH (n:Document {id: $docId})"),
    ]:
        total = 0
        while True:
            query = f"""
                {match}
                WITH n LIMIT 10000
                DETACH DELETE n
                RETURN count(*) AS cnt
            """
            async with driver.session(database=database) as session:
                result = await session.run(query, docId=document_id)
                record = await result.single()
                batch = record["cnt"] if record else 0
                total += batch
                if batch < 10000:
                    break
        counts[label] = total

    logger.info("Document deleted", document_id=document_id, counts=counts)
    return counts
