"""Generated bridge keys and relationship endpoints share one explicit policy."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastmcp import Client
from pydantic import BaseModel
from mcp_neo4j_entity_graph.server import create_mcp_server


class BridgeNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_generated_keys_match_endpoints_and_preserve_case_by_default(self):
        model = {
            "nodes": [
                {"label": label, "key_property": {"name": "name", "type": "STRING"}}
                for label in ("Product", "Facility")
            ],
            "relationships": [{"type": "MADE_AT", "start_node_label": "Product", "end_node_label": "Facility"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            async with Client(create_mcp_server(None)) as client:
                for policy in (None, {"Product": "strip_lower"}):
                    path = Path(directory) / 'schema.py'
                    args = {"modeling_output": json.dumps(model), "output_path": str(path)}
                    if policy is not None:
                        args["key_normalization"] = policy
                    await client.call_tool('convert_schema', args)
                    spec = importlib.util.spec_from_file_location('bridge_test_models', path)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[spec.name] = module
                    try:
                        exec(compile(path.read_text(), str(path), 'exec'), module.__dict__)
                        classes = [v for v in vars(module).values() if isinstance(v, type) and issubclass(v, BaseModel)]
                        product = next(c for c in classes if getattr(c, '_node_label', None) == 'Product')
                        facility = next(c for c in classes if getattr(c, '_node_label', None) == 'Facility')
                        rel = next(c for c in classes if getattr(c, '_relationship_type', None) == 'MADE_AT')
                        expected = 'aurora' if policy else 'Aurora'
                        self.assertEqual(expected, product(name=' Aurora ').name)
                        self.assertEqual('CaseID', facility(name=' CaseID ').name)
                        fields = rel.model_fields
                        values = {k: (' Aurora ' if 'product' in k else ' CaseID ') for k in fields}
                        parsed = rel(**values).model_dump()
                        self.assertEqual({expected, 'CaseID'}, set(parsed.values()))
                    finally:
                        sys.modules.pop(spec.name, None)

    async def test_unknown_label_policy_is_rejected(self):
        async with Client(create_mcp_server(None)) as client:
            with self.assertRaisesRegex(Exception, 'Unknown entity label'):
                await client.call_tool('convert_schema', {
                    'modeling_output': '{"nodes": []}',
                    'output_path': '/tmp/invalid-bridge-schema.py',
                    'key_normalization': {'Typo': 'strip_lower'},
                })
