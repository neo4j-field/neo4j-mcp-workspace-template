"""The live runner must not turn missing/failed extraction into a perfect score."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mcp_neo4j_entity_graph.models import ChunkExtractionResult, ChunkExtractionOutcome
from tests.golden.run_extraction import run


class GoldenRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_model_outputs_are_exported_as_empty_not_reference_facts(self):
        async def empty(chunk, _schema, _output_model):
            return ChunkExtractionResult(chunk_id=chunk.id, outcome=ChunkExtractionOutcome.EMPTY)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'candidate.json'
            with patch('tests.golden.run_extraction.load_dotenv'), patch.dict(
                'os.environ', {'EXTRACTION_MODEL': 'configured-test-model'}
            ), patch('tests.golden.run_extraction.TextExtractor') as extractor:
                extractor.return_value.extract_chunk = AsyncMock(side_effect=empty)
                await run(output)
            candidate = json.loads(output.read_text())
            self.assertEqual(3, len(candidate['cases']))
            self.assertTrue(all(not c['entities'] and not c['relationships'] for c in candidate['cases']))
            self.assertEqual('configured-test-model', candidate['metadata']['model'])
            self.assertEqual(3, extractor.return_value.extract_chunk.await_count)

    async def test_failed_source_does_not_produce_a_scorable_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'candidate.json'
            with patch('tests.golden.run_extraction.load_dotenv'), patch.dict(
                'os.environ', {'EXTRACTION_MODEL': 'configured-test-model'}
            ), patch('tests.golden.run_extraction.TextExtractor') as extractor:
                extractor.return_value.extract_chunk = AsyncMock(return_value=ChunkExtractionResult(
                    chunk_id='maintenance-1', outcome=ChunkExtractionOutcome.FAILED,
                    error='test provider failure',
                ))
                with self.assertRaisesRegex(RuntimeError, 'test provider failure'):
                    await run(output)
            self.assertFalse(output.exists())
