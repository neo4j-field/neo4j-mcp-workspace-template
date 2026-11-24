"""EXT-002 content/config identity and rapid schema edits must invalidate reuse."""
import os
import tempfile
import unittest
from pathlib import Path

from mcp_neo4j_entity_graph.base_extractor import load_extraction_output_model
from mcp_neo4j_entity_graph.extraction_identity import extraction_fingerprint, source_fingerprint
from mcp_neo4j_entity_graph.models import ClassifiedChunk, ChunkType


class ExtractionIdentityTests(unittest.TestCase):
    def test_source_content_and_visual_inputs_change_identity(self):
        chunk = ClassifiedChunk(id='one', chunk_type=ChunkType.TEXT, text='original')
        first = source_fingerprint(chunk)
        for field, value in [('text', 'changed'), ('image_base64', 'new image'),
                             ('section_context', 'new section'), ('caption', 'new caption')]:
            self.assertNotEqual(first, source_fingerprint(chunk.model_copy(update={field: value})))
        self.assertEqual(first, source_fingerprint(chunk.model_copy()))

    def test_schema_model_and_configuration_change_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            schema = Path(directory) / 'schema.py'
            schema.write_text('# one')
            params = dict(model='configured-model', source_label='Chunk',
                          property_policy='preserve_existing', pass_type='full', pass_number=1)
            snapshot = schema.read_bytes()
            first = extraction_fingerprint(schema, **params)
            for key, value in [('model', 'another-model'), ('source_label', 'Page'),
                               ('property_policy', 'overwrite'), ('pass_number', 2)]:
                self.assertNotEqual(first, extraction_fingerprint(schema, **{**params, key: value}))
            schema.write_text('# two')
            self.assertNotEqual(first, extraction_fingerprint(schema, **params))
            self.assertEqual(first, extraction_fingerprint(schema, schema_source=snapshot, **params))

    def test_same_size_same_timestamp_schema_edit_loads_new_source(self):
        with tempfile.TemporaryDirectory() as directory:
            schema = Path(directory) / 'schema.py'
            source = 'from pydantic import BaseModel\nclass ExtractionOutput(BaseModel):\n    value: str = "aa"\n'
            schema.write_text(source)
            timestamp = schema.stat()
            self.assertEqual('aa', load_extraction_output_model(str(schema))().value)
            schema.write_text(source.replace('"aa"', '"bb"'))
            os.utime(schema, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
            self.assertEqual('bb', load_extraction_output_model(str(schema))().value)
