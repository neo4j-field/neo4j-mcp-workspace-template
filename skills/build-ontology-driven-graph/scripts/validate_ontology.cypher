// Ontology DB validator — read-only.
//
// Returns 0 rows when the ontology is valid. Any returned row is an issue.
// Pass the ontology name as parameter $name.
// Run via: ontology_read_neo4j_cypher(query=<this file's contents>, params={"name": "<ontology>"})
//
// Schema reference: ../references/ontology-db-schema.md
// Reset/teardown queries: see ../references/ontology-db-schema.md
//
// Each row: { check, severity, entity, message }
//   - check:    machine-readable check id (e.g. "missing_key_property")
//   - severity: "error" (must fix before extracting) or "warning" (extraction will work but quality may suffer)
//   - entity:   the offending node identifier (NodeType/RelationshipType/PropertyDef name)
//   - message:  human-readable description for the user
//
// IMPORTANT: this file must contain no Cypher write keywords (the seven words
// matched by the read-only gate's regex) anywhere — including in comments or
// string literals — because read_neo4j_cypher applies a case-insensitive
// whole-word filter on the raw query text. Use synonyms in user-facing
// messages, e.g. "mark", "include", "combine", "specify" instead of write verbs.

// 1. NodeType missing key property
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(nt:NodeType)
WHERE NOT EXISTS {
  MATCH (nt)-[:HAS_PROPERTY]->(pd:PropertyDef)
  WHERE pd.is_key = true
}
RETURN
  'missing_key_property' AS check,
  'error' AS severity,
  nt.name AS entity,
  'NodeType "' + nt.name + '" has no PropertyDef with is_key=true. Every entity type needs exactly one key property used to combine duplicate entities.' AS message

UNION ALL

// 2. NodeType with multiple key properties
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(nt:NodeType)-[:HAS_PROPERTY]->(pd:PropertyDef)
WHERE pd.is_key = true
WITH nt, count(pd) AS keys
WHERE keys > 1
RETURN
  'multiple_key_properties' AS check,
  'error' AS severity,
  nt.name AS entity,
  'NodeType "' + nt.name + '" has ' + toString(keys) + ' key properties; expected exactly 1. Mark is_key=false on all but one.' AS message

UNION ALL

// 3. RelationshipType missing FROM endpoint
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(rt:RelationshipType)
WHERE NOT EXISTS { MATCH (rt)-[:FROM]->(:NodeType) }
RETURN
  'missing_from_endpoint' AS check,
  'error' AS severity,
  rt.name AS entity,
  'RelationshipType "' + rt.name + '" has no :FROM endpoint. Every relationship needs a source NodeType.' AS message

UNION ALL

// 4. RelationshipType missing TO endpoint
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(rt:RelationshipType)
WHERE NOT EXISTS { MATCH (rt)-[:TO]->(:NodeType) }
RETURN
  'missing_to_endpoint' AS check,
  'error' AS severity,
  rt.name AS entity,
  'RelationshipType "' + rt.name + '" has no :TO endpoint. Every relationship needs a target NodeType.' AS message

UNION ALL

// 5. RelationshipType with multiple FROM endpoints
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(rt:RelationshipType)-[:FROM]->(:NodeType)
WITH rt, count(*) AS n
WHERE n > 1
RETURN
  'multiple_from_endpoints' AS check,
  'error' AS severity,
  rt.name AS entity,
  'RelationshipType "' + rt.name + '" has ' + toString(n) + ' :FROM endpoints; expected exactly 1.' AS message

UNION ALL

// 6. RelationshipType with multiple TO endpoints
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(rt:RelationshipType)-[:TO]->(:NodeType)
WITH rt, count(*) AS n
WHERE n > 1
RETURN
  'multiple_to_endpoints' AS check,
  'error' AS severity,
  rt.name AS entity,
  'RelationshipType "' + rt.name + '" has ' + toString(n) + ' :TO endpoints; expected exactly 1.' AS message

UNION ALL

// 7. Relationship endpoint NodeType not contained in this ontology
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(rt:RelationshipType)
MATCH (rt)-[:FROM|TO]->(nt:NodeType)
WHERE NOT (o)-[:CONTAINS]->(nt)
RETURN
  'endpoint_outside_ontology' AS check,
  'error' AS severity,
  rt.name AS entity,
  'RelationshipType "' + rt.name + '" has endpoint "' + nt.name + '" which is not in ontology "' + $name + '".' AS message

UNION ALL

// 8. PropertyDef with invalid type
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(parent)
MATCH (parent)-[:HAS_PROPERTY]->(pd:PropertyDef)
WHERE pd.type IS NULL OR NOT pd.type IN ['STRING', 'INTEGER', 'FLOAT', 'BOOLEAN']
RETURN
  'invalid_property_type' AS check,
  'error' AS severity,
  parent.name + '.' + pd.name AS entity,
  'PropertyDef "' + pd.name + '" on ' + parent.name + ' has type "' + coalesce(pd.type, '<null>') + '". Must be STRING, INTEGER, FLOAT, or BOOLEAN.' AS message

UNION ALL

// 9. PropertyDef with unknown normalizer tag
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(parent)
MATCH (parent)-[:HAS_PROPERTY]->(pd:PropertyDef)
WITH parent, pd,
     coalesce(pd.normalizers, CASE WHEN pd.normalizer IS NOT NULL THEN [pd.normalizer] ELSE [] END) AS tags
UNWIND tags AS tag
WITH parent, pd, tag
WHERE NOT tag IN [
  'whitespace','strip_the','strip_acronym_suffix','lowercase','uppercase','titlecase',
  'email','phone','url','date','monetary_amount','percentage','integer',
  'alias_map','blocklist','regex_normalize','regex_skip','enum_validate','compose_name_from_fields'
]
RETURN
  'invalid_normalizer_tag' AS check,
  'error' AS severity,
  parent.name + '.' + pd.name AS entity,
  'PropertyDef "' + pd.name + '" on ' + parent.name + ' has unknown normalizer "' + tag + '". See references/ontology-db-schema.md for the valid registry.' AS message

UNION ALL

// 10. alias_map normalizer without USES_ALIAS_MAP link
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(parent)
MATCH (parent)-[:HAS_PROPERTY]->(pd:PropertyDef)
WHERE (pd.normalizer = 'alias_map' OR 'alias_map' IN coalesce(pd.normalizers, []))
  AND NOT EXISTS { MATCH (pd)-[:USES_ALIAS_MAP]->(:AliasMap) }
RETURN
  'alias_map_missing_link' AS check,
  'error' AS severity,
  parent.name + '.' + pd.name AS entity,
  'PropertyDef "' + pd.name + '" uses alias_map normalizer but is not linked to any :AliasMap via :USES_ALIAS_MAP.' AS message

UNION ALL

// 11. blocklist normalizer without USES_BLOCKLIST link
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(parent)
MATCH (parent)-[:HAS_PROPERTY]->(pd:PropertyDef)
WHERE (pd.normalizer = 'blocklist' OR 'blocklist' IN coalesce(pd.normalizers, []))
  AND NOT EXISTS { MATCH (pd)-[:USES_BLOCKLIST]->(:Blocklist) }
RETURN
  'blocklist_missing_link' AS check,
  'error' AS severity,
  parent.name + '.' + pd.name AS entity,
  'PropertyDef "' + pd.name + '" uses blocklist normalizer but is not linked to any :Blocklist via :USES_BLOCKLIST.' AS message

UNION ALL

// 12. regex_normalize missing pattern or replacement
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(parent)
MATCH (parent)-[:HAS_PROPERTY]->(pd:PropertyDef)
WHERE (pd.normalizer = 'regex_normalize' OR 'regex_normalize' IN coalesce(pd.normalizers, []))
  AND (pd.regex_pattern IS NULL OR pd.regex_replacement IS NULL)
RETURN
  'regex_normalize_missing_config' AS check,
  'error' AS severity,
  parent.name + '.' + pd.name AS entity,
  'PropertyDef "' + pd.name + '" uses regex_normalize but is missing regex_pattern or regex_replacement.' AS message

UNION ALL

// 13. regex_skip missing pattern
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(parent)
MATCH (parent)-[:HAS_PROPERTY]->(pd:PropertyDef)
WHERE (pd.normalizer = 'regex_skip' OR 'regex_skip' IN coalesce(pd.normalizers, []))
  AND pd.regex_pattern IS NULL
RETURN
  'regex_skip_missing_config' AS check,
  'error' AS severity,
  parent.name + '.' + pd.name AS entity,
  'PropertyDef "' + pd.name + '" uses regex_skip but has no regex_pattern.' AS message

UNION ALL

// 14. enum_validate missing or empty enum_values
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(parent)
MATCH (parent)-[:HAS_PROPERTY]->(pd:PropertyDef)
WHERE (pd.normalizer = 'enum_validate' OR 'enum_validate' IN coalesce(pd.normalizers, []))
  AND (pd.enum_values IS NULL OR size(pd.enum_values) = 0)
RETURN
  'enum_validate_missing_values' AS check,
  'error' AS severity,
  parent.name + '.' + pd.name AS entity,
  'PropertyDef "' + pd.name + '" uses enum_validate but has no (or empty) enum_values list.' AS message

UNION ALL

// 15. compose_name_from_fields missing name_template
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(parent)
MATCH (parent)-[:HAS_PROPERTY]->(pd:PropertyDef)
WHERE (pd.normalizer = 'compose_name_from_fields' OR 'compose_name_from_fields' IN coalesce(pd.normalizers, []))
  AND pd.name_template IS NULL
RETURN
  'compose_name_missing_template' AS check,
  'error' AS severity,
  parent.name + '.' + pd.name AS entity,
  'PropertyDef "' + pd.name + '" uses compose_name_from_fields but has no name_template.' AS message

UNION ALL

// 16. AliasMap with no Alias entries (warning — not fatal but the normalizer will be a no-op)
MATCH (o:Ontology {name: $name})-[:DEFINES]->(am:AliasMap)
WHERE NOT EXISTS { MATCH (am)-[:HAS_ALIAS]->(:Alias) }
RETURN
  'alias_map_empty' AS check,
  'warning' AS severity,
  am.name AS entity,
  'AliasMap "' + am.name + '" has no aliases. Properties using it will not normalize anything.' AS message

UNION ALL

// 17. Blocklist with no BlockedTerm entries (warning)
MATCH (o:Ontology {name: $name})-[:DEFINES]->(bl:Blocklist)
WHERE NOT EXISTS { MATCH (bl)-[:HAS_TERM]->(:BlockedTerm) }
RETURN
  'blocklist_empty' AS check,
  'warning' AS severity,
  bl.name AS entity,
  'Blocklist "' + bl.name + '" has no terms. Properties using it will not skip anything.' AS message

UNION ALL

// 18. Ontology has no NodeTypes (warning — extraction would yield nothing)
MATCH (o:Ontology {name: $name})
WHERE NOT EXISTS { MATCH (o)-[:CONTAINS]->(:NodeType) }
RETURN
  'ontology_no_node_types' AS check,
  'warning' AS severity,
  o.name AS entity,
  'Ontology "' + o.name + '" contains no NodeTypes. Include at least one entity type before extracting.' AS message

UNION ALL

// 19. Ontology not found at all
WITH 1 AS _seed
OPTIONAL MATCH (named:Ontology {name: $name})
WITH count(named) AS found
WHERE found = 0
RETURN
  'ontology_not_found' AS check,
  'error' AS severity,
  $name AS entity,
  'No :Ontology node with name "' + $name + '" exists in this database. List existing ones with: MATCH (o:Ontology) RETURN o.name' AS message
