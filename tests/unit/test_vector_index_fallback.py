"""BUG-004: vector index creation must verify and report the real index."""

import unittest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp import Client

from mcp_neo4j_lexical_graph.server import _ensure_vector_index, create_mcp_server
from mcp_neo4j_lexical_graph.embedding_identity import embedding_space, input_hash


class _Result:
    def __init__(self, record=None, rows=None):
        self.record = record
        self.rows = rows or []

    async def consume(self):
        return None

    async def single(self):
        return self.record

    async def data(self):
        return self.rows


class _Session:
    def __init__(self, driver):
        self.driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def run(self, query, **_kwargs):
        self.driver.queries.append(query)
        if "AS missing_inputs" in query:
            return _Result({"missing_inputs": 0})
        if "RETURN elementId(c) AS eid" in query:
            return _Result(rows=getattr(self.driver, 'rows', []))
        if "RETURN size(c.`text_embedding`) AS dims" in query:
            return _Result({"dims": 3})
        if query.startswith("SHOW FULLTEXT INDEXES"):
            return _Result({"state":"ONLINE", "entityType":"NODE", "labelsOrTypes":["Chunk"], "properties":["text"]})
        if query.startswith("SHOW VECTOR INDEXES"):
            return _Result(self.driver.record)
        if "WITH [" in query and self.driver.reject_prefilter:
            raise RuntimeError("unsupported prefilter syntax")
        if "WITH [" not in query and self.driver.reject_plain:
            if isinstance(self.driver.reject_plain, Exception):
                raise self.driver.reject_plain
            raise RuntimeError("plain index creation failed")
        return _Result()


class _Driver:
    def __init__(self, *, reject_prefilter=False, reject_plain=False, record=None):
        self.reject_prefilter = reject_prefilter
        self.reject_plain = reject_plain
        self.record = record
        self.queries = []

    def session(self, **_kwargs):
        return _Session(self)


class VectorIndexFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_tool_call_repairs_index_without_new_embeddings(self):
        driver = _Driver()
        space = embedding_space('text-embedding-3-small')
        driver.rows = [dict(eid='one', text='verified input', vector_dims=3, dims=3,
                            space=space.fingerprint, cached_model=space.model, provider=space.provider,
                            input_hash=input_hash('verified input'), labels=['Chunk'])]
        server = create_mcp_server(driver, database="neo4j", process_pool=MagicMock())
        ensure = AsyncMock(return_value={"name": "chunk_text_embedding", "state": "ONLINE", "mode": "plain"})
        index = {'entityType':'NODE','labelsOrTypes':['Chunk'],'properties':['text_embedding'],
                 'options':{'indexConfig':{'vector.dimensions':3,'vector.similarity_function':'cosine'}}}
        with patch("mcp_neo4j_lexical_graph.server._ensure_vector_index", ensure), patch(
            "mcp_neo4j_lexical_graph.server._embedding_index_info", AsyncMock(return_value=index)
        ), patch("mcp_neo4j_lexical_graph.server.ChunkEmbedder.embed_many", AsyncMock()) as provider:

            async with Client(server) as client:
                result = await client.call_tool("embed_chunks", {})
        provider.assert_not_awaited()
        self.assertFalse(result.is_error, result)
        payload = json.loads(result.content[0].text)
        self.assertEqual("success", payload["status"])
        self.assertEqual(0, payload["embedded"])
        self.assertEqual("plain", payload["vector_index_mode"])
        self.assertEqual(["documentName", "type"], ensure.await_args.args[-1])

    async def test_supported_prefilter(self):
        driver = _Driver(record={"state": "ONLINE", "createStatement": "CREATE VECTOR INDEX x FOR (c:Chunk) ON c.text_embedding WITH [c.documentName] OPTIONS {}"})
        info = await _ensure_vector_index(driver, "neo4j", "x", "Chunk", "text_embedding", 3, ["documentName", "type"])
        self.assertEqual({"name": "x", "state": "ONLINE", "mode": "prefiltered"}, info)
        self.assertEqual(2, len(driver.queries))

    async def test_unsupported_prefilter_falls_back(self):
        driver = _Driver(reject_prefilter=True, record={"state": "POPULATING", "createStatement": "CREATE VECTOR INDEX x FOR (c:Chunk) ON c.text_embedding OPTIONS {}"})
        info = await _ensure_vector_index(driver, "neo4j", "x", "Chunk", "text_embedding", 3, ["documentName", "type"])
        self.assertEqual("plain", info["mode"])
        self.assertEqual("POPULATING", info["state"])
        self.assertEqual(3, len(driver.queries))

    async def test_missing_index_is_error(self):
        driver = _Driver(record=None)
        with self.assertRaisesRegex(RuntimeError, "was not created"):
            await _ensure_vector_index(driver, "neo4j", "x", "Chunk", "text_embedding", 3, [])

    async def test_both_creation_paths_fail(self):
        driver = _Driver(reject_prefilter=True, reject_plain=True)
        with self.assertRaisesRegex(RuntimeError, "failed with prefilters"):
            await _ensure_vector_index(driver, "neo4j", "x", "Chunk", "text_embedding", 3, ["documentName"])


if __name__ == "__main__":
    unittest.main()


class VectorIndexCreationRaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_equivalent_rule_race_still_verifies_named_index(self):
        class EquivalentRuleRace(Exception):
            code = "Neo.ClientError.Schema.EquivalentSchemaRuleAlreadyExists"
        driver = _Driver(reject_prefilter=True, reject_plain=EquivalentRuleRace(), record={
            'state':'ONLINE','createStatement':'CREATE VECTOR INDEX x FOR (c:Chunk) ON c.text_embedding OPTIONS {}'})
        info = await _ensure_vector_index(driver, 'neo4j', 'x', 'Chunk', 'text_embedding', 3, ['documentName'])
        self.assertEqual('plain', info['mode'])
        self.assertEqual('ONLINE', info['state'])
