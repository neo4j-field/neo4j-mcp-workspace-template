"""Ontology interchange rejects unsupported/lost semantics before graph writes."""

import json
import unittest
from unittest.mock import MagicMock

from mcp_neo4j_entity_graph.ontology_spec import (
    EXTENSION,
    SCHEMA_URI,
    parse_document,
    serialize_document,
    validate_document,
    import_document,
)


def fixture():
    return {
        "schema": SCHEMA_URI,
        "version": "poc-1",
        "id": "n4-fixture",
        "nodes": {
            "person-id": {
                "label": "N4Person",
                "description": "An employee",
                "properties": {
                    "identifier": {
                        "name": "name",
                        "type": "STRING",
                        "key": True,
                        "extensions": {
                            "custom": {
                                EXTENSION: {
                                    "normalizers": [
                                        "whitespace",
                                        "lowercase",
                                        "alias_map",
                                        "blocklist",
                                    ],
                                    "alias_map_name": "N4Aliases",
                                    "blocklist_name": "N4Blocked",
                                }
                            }
                        },
                    },
                    "age": {"type": "INTEGER"},
                },
            },
            "org-id": {
                "labels": {"identifier": "N4Org"},
                "properties": {
                    "name": {"type": "STRING", "key": True},
                },
            },
        },
        "relationships": {
            "employment": {
                "type": "N4_WORKS_AT",
                "from": {"node": "person-id"},
                "to": {"node": "org-id"},
                "properties": {"active": {"type": "BOOLEAN", "must_exist": True}},
            }
        },
        "extensions": {
            "custom": {
                EXTENSION: {
                    "alias_maps": {"N4Aliases": {"bob": "robert"}},
                    "blocklists": {"N4Blocked": ["unknown"]},
                }
            }
        },
    }


class OntologySpecTests(unittest.IsolatedAsyncioTestCase):
    def test_json_yaml_equivalence_and_ordered_normalizers(self):
        original = fixture()
        self.assertEqual(original, parse_document(json.dumps(original)))
        self.assertEqual(original, parse_document(serialize_document(original)))
        payload = validate_document(original)
        self.assertEqual("name", payload["nodes"][0]["properties"][0]["name"])
        self.assertEqual(
            ["whitespace", "lowercase", "alias_map", "blocklist"],
            payload["nodes"][0]["properties"][0]["normalizers"],
        )
        self.assertEqual("N4Person", payload["relationships"][0]["from"])
        self.assertTrue(payload["relationships"][0]["properties"][0]["required"])

    def test_minimal_ontology_without_normalizers(self):
        doc = {
            "schema": SCHEMA_URI,
            "version": "1",
            "id": "simple",
            "nodes": {
                "p": {
                    "label": "Person",
                    "properties": {"name": {"type": "STRING", "key": True}},
                }
            },
        }
        self.assertEqual("Person", validate_document(doc)["nodes"][0]["name"])

    def test_multiple_composed_name_targets_are_rejected(self):
        doc = fixture()
        for name in ["first", "second"]:
            doc["nodes"]["org-id"]["properties"][name] = {
                "type": "STRING",
                "extensions": {
                    "custom": {
                        EXTENSION: {
                            "normalizers": ["compose_name_from_fields"],
                            "name_template": "{name}",
                        }
                    }
                },
            }
        with self.assertRaisesRegex(ValueError, "only one compose"):
            validate_document(doc)

    def test_filename_unsafe_id_and_recursive_yaml_rejected(self):
        doc = fixture()
        doc["id"] = "../outside"
        with self.assertRaisesRegex(ValueError, "filename-safe"):
            validate_document(doc)
        with self.assertRaisesRegex(ValueError, "aliases are unsupported"):
            parse_document("recursive: &ref [*ref]")

    def test_single_property_explicit_key_and_exists_constraints(self):
        doc = fixture()
        node = doc["nodes"]["org-id"]
        del node["properties"]["name"]["key"]
        node["constraints"] = {"pk": {"type": "KEY", "properties": ["name"]}}
        self.assertTrue(validate_document(doc)["nodes"][1]["properties"][0]["is_key"])

    def test_invalid_documents_fail_with_field_paths(self):
        cases = []
        doc = fixture()
        doc["schema"] = "https://neo4j.com/docs/ontology-graph-spec/current/schema.json"
        cases.append((doc, "schema"))
        doc = fixture()
        doc["nodes"]["org-id"]["properties"]["name"]["type"] = "DATE"
        cases.append((doc, "type"))
        doc = fixture()
        doc["nodes"]["org-id"]["labels"]["implied"] = ["Other"]
        cases.append((doc, "labels.implied"))
        doc = fixture()
        doc["relationships"]["employment"]["from"]["node"] = "missing"
        cases.append((doc, "from.node"))
        doc = fixture()
        doc["relationships"]["employment"]["from"]["max_count"] = 1
        cases.append((doc, "from.max_count"))
        doc = fixture()
        doc["nodes"]["org-id"]["properties"]["name"]["unique"] = True
        cases.append((doc, "unique"))
        doc = fixture()
        doc["nodes"]["org-id"]["properties"]["name"]["key"] = False
        cases.append((doc, "exactly one key"))
        doc = fixture()
        doc["nodes"]["org-id"]["constraints"] = {
            "pk": {"type": "KEY", "properties": ["name", "other"]}
        }
        cases.append((doc, "constraints.pk"))
        doc = fixture()
        doc["nodes"]["org-id"]["properties"]["name"]["pattern"] = ".+"
        cases.append((doc, "pattern"))
        doc = fixture()
        doc["extensions"]["data_source_tables"] = {}
        cases.append((doc, "data_source_tables"))
        doc = fixture()
        doc["nodes"]["org-id"]["label"] = "Both"
        cases.append((doc, "not both"))
        doc = fixture()
        doc["nodes"]["org-id"]["labels"]["identifier"] = "Document"
        cases.append((doc, "Reserved entity"))
        doc = fixture()
        doc["nodes"]["person-id"]["properties"]["identifier"]["extensions"]["custom"][
            EXTENSION
        ]["normalizers"] = ["invented"]
        cases.append((doc, "unknown normalizer"))
        doc = fixture()
        doc["extensions"]["custom"][EXTENSION]["alias_maps"] = {}
        cases.append((doc, "alias_map_name"))
        doc = fixture()
        doc["extensions"]["custom"][EXTENSION]["blocklists"]["N4Blocked"] = [1]
        cases.append((doc, "blocklists"))
        doc = fixture()
        prop = doc["nodes"]["org-id"]["properties"]["name"]
        prop["extensions"] = {
            "custom": {EXTENSION: {"normalizers": ["regex_skip"], "regex_pattern": "["}}
        }
        cases.append((doc, "invalid regex"))
        doc = fixture()
        doc["nodes"]["org-id"]["properties"]["second"] = {
            "type": "STRING",
            "name": "name",
        }
        cases.append((doc, "duplicate"))
        for doc, expected in cases:
            with (
                self.subTest(expected=expected),
                self.assertRaisesRegex(ValueError, expected),
            ):
                validate_document(doc)

    def test_duplicate_mapping_keys_rejected_in_both_formats(self):
        for content in ["id: one\nid: two\n", '{"id":"one", "id":"two"}']:
            with self.assertRaisesRegex(ValueError, "Duplicate mapping key"):
                parse_document(content)

    async def test_invalid_payload_never_opens_database_session(self):
        driver = MagicMock()
        doc = fixture()
        doc["relationships"]["employment"]["to"]["node"] = "missing"
        with self.assertRaisesRegex(ValueError, "unknown node"):
            await import_document(driver, "neo4j", doc)
        driver.session.assert_not_called()

    def test_unsafe_yaml_and_unsupported_format_fail(self):
        with self.assertRaisesRegex(ValueError, "Invalid YAML"):
            parse_document("!!python/object/apply:os.system [echo unsafe]")
        with self.assertRaisesRegex(ValueError, "format"):
            serialize_document(fixture(), "xml")
