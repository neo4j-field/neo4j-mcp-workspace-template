// WF-004 deterministic ontology fixture.
//
// This deliberately exercises every relationship in the ontology contract so
// the Desktop write, read-back, validation, and schema-generation paths cannot
// silently drift apart. Every node is tagged for exact teardown.
CREATE (o:Ontology {
  name: $ontologyName,
  description: 'WF-004 ontology workflow contract fixture',
  version: 'v1',
  testRunId: $testRunId
})
CREATE (agreement:NodeType {
  name: $agreementType,
  description: 'An agreement signed by a party',
  testRunId: $testRunId
})
CREATE (agreementKey:PropertyDef {
  name: $agreementKey,
  type: 'STRING',
  description: 'Stable agreement identifier',
  required: true,
  is_key: true,
  normalizer: 'whitespace',
  testRunId: $testRunId
})
CREATE (jurisdiction:PropertyDef {
  name: $jurisdictionProperty,
  type: 'STRING',
  description: 'Governing jurisdiction',
  required: false,
  is_key: false,
  normalizer: 'alias_map',
  testRunId: $testRunId
})
CREATE (party:NodeType {
  name: $partyType,
  description: 'A party that signs an agreement',
  testRunId: $testRunId
})
CREATE (partyKey:PropertyDef {
  name: $partyKey,
  type: 'STRING',
  description: 'Stable party name',
  required: true,
  is_key: true,
  normalizer: 'blocklist',
  testRunId: $testRunId
})
CREATE (signed:RelationshipType {
  name: $relationshipType,
  description: 'Connects a party to an agreement they signed',
  testRunId: $testRunId
})
CREATE (signedDate:PropertyDef {
  name: $relationshipProperty,
  type: 'STRING',
  description: 'Date the agreement was signed',
  required: false,
  is_key: false,
  normalizer: 'date',
  testRunId: $testRunId
})
CREATE (aliasMap:AliasMap {
  name: $aliasMap,
  description: 'WF-004 jurisdiction aliases',
  testRunId: $testRunId
})
CREATE (alias:Alias {
  from: 'UK',
  to: 'United Kingdom',
  testRunId: $testRunId
})
CREATE (blocklist:Blocklist {
  name: $blocklist,
  description: 'WF-004 generic non-parties',
  testRunId: $testRunId
})
CREATE (blocked:BlockedTerm {
  value: 'the parties',
  testRunId: $testRunId
})
CREATE (o)-[:CONTAINS]->(agreement)
CREATE (o)-[:CONTAINS]->(party)
CREATE (o)-[:CONTAINS]->(signed)
CREATE (o)-[:DEFINES]->(aliasMap)
CREATE (o)-[:DEFINES]->(blocklist)
CREATE (agreement)-[:HAS_PROPERTY]->(agreementKey)
CREATE (agreement)-[:HAS_PROPERTY]->(jurisdiction)
CREATE (party)-[:HAS_PROPERTY]->(partyKey)
CREATE (signed)-[:HAS_PROPERTY]->(signedDate)
CREATE (signed)-[:FROM]->(party)
CREATE (signed)-[:TO]->(agreement)
CREATE (jurisdiction)-[:USES_ALIAS_MAP]->(aliasMap)
CREATE (partyKey)-[:USES_BLOCKLIST]->(blocklist)
CREATE (aliasMap)-[:HAS_ALIAS]->(alias)
CREATE (blocklist)-[:HAS_TERM]->(blocked)
