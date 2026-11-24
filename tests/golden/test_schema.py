"""Ensure the golden reference and extraction schema agree."""

import json
import sys
import unittest
from pathlib import Path

from mcp_neo4j_entity_graph.base_extractor import (
    load_extraction_output_model,
    schema_from_pydantic_module,
)


class GoldenSchemaTests(unittest.TestCase):
    def test_reference_types_exist_in_extraction_schema(self):
        directory = Path(__file__).parent
        load_extraction_output_model(str(directory / "synthetic_schema.py"))
        schema = schema_from_pydantic_module(sys.modules["extraction_models"])
        reference = json.loads((directory / "synthetic_extraction.json").read_text())
        labels = {item.label for item in schema.entity_types}
        types = {item.type for item in schema.relationship_types}
        for case in reference["cases"]:
            for entity in case["entities"]:
                self.assertIn(entity["label"], labels)
            for relationship in case["relationships"]:
                self.assertIn(relationship["type"], types)
                self.assertIn(relationship["source"][0], labels)
                self.assertIn(relationship["target"][0], labels)


if __name__ == "__main__":
    unittest.main()
