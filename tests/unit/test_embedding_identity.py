"""Embedding cache reuse depends on exact input and coherent vector-space identity."""
import unittest
from unittest.mock import patch

from mcp_neo4j_lexical_graph.embedding_identity import (
    embedding_space, input_hash, cache_matches, validate_vectors,
    check_preserved_space, check_overlaps,
)


class EmbeddingIdentityTests(unittest.TestCase):
    def row(self, space, text='doc section text'):
        return dict(eid='one', text=text, vector_dims=3, dims=3, space=space.fingerprint,
                    provider=space.provider, cached_model=space.model, input_hash=input_hash(text), labels=['Chunk'])

    def test_exact_input_model_route_and_dimension_identity(self):
        space = embedding_space('text-embedding-3-small')
        row = self.row(space)
        self.assertTrue(cache_matches(row, space))
        for change in [dict(text='changed context text'), dict(space=None), dict(dims=99), dict(vector_dims=2), dict(input_hash=None)]:
            self.assertFalse(cache_matches({**row, **change}, space))
        self.assertFalse(cache_matches(row, embedding_space('text-embedding-3-large')))
        self.assertFalse(cache_matches(row, embedding_space('text-embedding-3-small', 3)))
        with patch.dict('os.environ', {'OPENAI_API_BASE':'https://different.invalid/v1'}):
            self.assertNotEqual(space.fingerprint, embedding_space('text-embedding-3-small').fingerprint)

    def test_partial_duplicate_invalid_or_mixed_vectors_are_rejected(self):
        rows = [dict(eid='one'),dict(eid='two')]
        for result in [[('one',[1,0,0])], [('one',[1,0,0]),('one',[1,0,0])],
                       [('one',[1,0,0]),('two',[1,0])], [('one',[0,0,0]),('two',[1,0,0])],
                       [('one',[float('nan'),0,0]),('two',[1,0,0])],
                       [('one',[1e40,0,0]),('two',[1,0,0])], [('one',[1e-100,0,0]),('two',[1,0,0])]]:
            with self.assertRaises(RuntimeError):
                validate_vectors(rows, result)
        self.assertEqual(3, validate_vectors(rows, [('one',[1,0,0]),('two',[0,1,0])], 3))

    def test_preserved_or_overlapping_indexes_cannot_mix_spaces(self):
        space = embedding_space('text-embedding-3-small')
        row = self.row(space)
        with self.assertRaisesRegex(RuntimeError, 'mix'):
            check_preserved_space([{**row,'space':None}], set(), space)
        self.assertEqual(set(), check_preserved_space([{**row,'space':None}], {'one'}, space))
        overlap = [dict(options={'indexConfig':{'vector.dimensions':3}})]
        with self.assertRaisesRegex(RuntimeError, 'another text_embedding'):
            check_overlaps(overlap, [{**row,'space':None}], space)
        with self.assertRaisesRegex(RuntimeError, 'dimensions'):
            check_overlaps(overlap, [row], space, 4)


class EmbeddingIdentityAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_requested_dimensions_are_forwarded_and_truncated_indexes_rejected(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from mcp_neo4j_lexical_graph.embedder import ChunkEmbedder
        response = SimpleNamespace(data=[{'index':0,'embedding':[1.,0.,0.]}])
        with patch('mcp_neo4j_lexical_graph.embedder.litellm.aembedding', AsyncMock(return_value=response)) as provider:
            embedder = ChunkEmbedder(dimensions=3)
            with self.assertRaisesRegex(ValueError, 'indexes'):
                await embedder.embed_texts_batch(['one','two'])
            self.assertEqual(3, provider.await_args.kwargs['dimensions'])

    async def test_constraint_conflict_and_connection_cause_remain_distinct(self):
        from mcp_neo4j_lexical_graph.embedding_identity import ensure_publication_constraint
        class Result:
            async def consume(self): pass
            async def single(self):
                return {'labelsOrTypes':['OtherLabel'],'properties':['id'],'type':'UNIQUENESS'}
        class Session:
            async def run(self, *_args, **_kwargs): return Result()
        with self.assertRaisesRegex(RuntimeError, 'incompatible definition'):
            await ensure_publication_constraint(Session())
        class Disconnected:
            async def run(self, *_args, **_kwargs): raise ConnectionError('fixture connection failure')
        with self.assertRaisesRegex(RuntimeError, 'fixture connection failure'):
            await ensure_publication_constraint(Disconnected())
