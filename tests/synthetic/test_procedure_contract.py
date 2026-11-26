"""Preserve the physical contract while passing narrower guidance to the model."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

from tests.synthetic.procedure_contract import assigned_procedure_ontology, PROCEDURE_DESCRIPTION, ASSIGNMENT_DESCRIPTION
from tests.synthetic.schemas import ontology_spec

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'mcp-neo4j-entity-graph/src'))
from mcp_neo4j_entity_graph.ontology_spec import validate_document
from mcp_neo4j_entity_graph.models import ExtractionSchema
from mcp_neo4j_entity_graph.schema_generator import generate_extraction_models_code


class AssignedProcedureContractTests(unittest.TestCase):
    def test_only_two_descriptions_change_and_source_is_independent(self):
        source = ontology_spec()
        original = deepcopy(source)
        result = assigned_procedure_ontology(source)
        self.assertEqual(original, source)
        result['nodes']['FixtureProcedure']['description'] = original['nodes']['FixtureProcedure']['description']
        result['relationships']['FIXTURE_USES_PROCEDURE']['description'] = original['relationships']['FIXTURE_USES_PROCEDURE']['description']
        self.assertEqual(original, result)
        result['nodes']['FixtureProcedure']['properties']['name']['type'] = 'OTHER'
        self.assertEqual(original, source)

    def test_descriptions_propagate_through_validation_and_generated_schema(self):
        payload = validate_document(assigned_procedure_ontology(ontology_spec()))
        schema = ExtractionSchema.model_validate(dict(
            entity_types=[dict(label=n['name'], description=n['description'],
                               key_property=next(p['name'] for p in n['properties'] if p['is_key']),
                               properties=n['properties']) for n in payload['nodes']],
            relationship_types=[dict(type=r['name'], description=r['description'],
                                     source_entity=r['from'], target_entity=r['to'],
                                     properties=r['properties']) for r in payload['relationships']]))
        self.assertEqual(PROCEDURE_DESCRIPTION, next(e.description for e in schema.entity_types if e.label == 'FixtureProcedure'))
        self.assertEqual(ASSIGNMENT_DESCRIPTION, next(r.description for r in schema.relationship_types if r.type == 'FIXTURE_USES_PROCEDURE'))
        code = generate_extraction_models_code(schema)
        self.assertIn('formally assigned', code)
        self.assertIn('Verification steps', code)


if __name__ == '__main__':
    unittest.main()
