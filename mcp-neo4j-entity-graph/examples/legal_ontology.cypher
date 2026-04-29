// Sample legal ontology — exercises every normalizer category.
// Run against the Ontology DB AFTER calling setup_ontology_db().
//
// Statements are independently self-contained (each MERGE re-binds via name lookup)
// so the file can be split on `;\n` and run as a sequence of separate transactions.
//
// Tests in this ontology:
//   Generic normalizer:         Contract.title (whitespace), Contract.signedDate (date),
//                               Contract.amount (monetary_amount), PARTY_TO.role (lowercase)
//   Parameterized alias_map:    Contract.jurisdiction (JURISDICTION_ALIASES)
//   Parameterized blocklist:    Party.name (NOT_A_PARTY)
//   regex_normalize:            Contract.caseNumber
//   enum_validate:              Contract.contractType
//   compose_name_from_fields:   Penalty (model-level)
//   Relationship + property:    Party PARTY_TO Contract (with role property)

// ── Ontology root ────────────────────────────────────────────────────────────
MERGE (o:Ontology {name: "legal_demo"})
SET o.description = "Demo legal ontology — contracts, parties, penalties",
    o.version = "v1",
    o.created_at = datetime();

// ── AliasMap: JURISDICTION_ALIASES ──────────────────────────────────────────
MATCH (o:Ontology {name: "legal_demo"})
MERGE (am:AliasMap {name: "JURISDICTION_ALIASES"})
SET am.description = "Map jurisdiction abbreviations to canonical names"
MERGE (o)-[:DEFINES]->(am)
WITH am
UNWIND [
  {from: "NY", to: "New York"},
  {from: "N.Y.", to: "New York"},
  {from: "CA", to: "California"},
  {from: "Cal.", to: "California"},
  {from: "DE", to: "Delaware"},
  {from: "Del.", to: "Delaware"}
] AS row
MERGE (a:Alias {from: row.from, to: row.to})
MERGE (am)-[:HAS_ALIAS]->(a);

// ── Blocklist: NOT_A_PARTY ──────────────────────────────────────────────────
MATCH (o:Ontology {name: "legal_demo"})
MERGE (bl:Blocklist {name: "NOT_A_PARTY"})
SET bl.description = "Generic placeholders that should not become Party nodes"
MERGE (o)-[:DEFINES]->(bl)
WITH bl
UNWIND ["the parties", "all parties", "third parties", "anyone"] AS term
MERGE (t:BlockedTerm {value: term})
MERGE (bl)-[:HAS_TERM]->(t);

// ── NodeType: Party ─────────────────────────────────────────────────────────
MATCH (o:Ontology {name: "legal_demo"})
MERGE (party:NodeType {name: "Party"})
SET party.description = "A natural or legal person bound by a contract"
MERGE (o)-[:CONTAINS]->(party);

MATCH (party:NodeType {name: "Party"})
MATCH (bl:Blocklist {name: "NOT_A_PARTY"})
MERGE (party)-[:HAS_PROPERTY]->(pd:PropertyDef {name: "name"})
SET pd.type = "STRING",
    pd.description = "Party's full legal name (no generic placeholders)",
    pd.required = true,
    pd.is_key = true,
    pd.normalizer = "blocklist"
MERGE (pd)-[:USES_BLOCKLIST]->(bl);

// ── NodeType: Contract ──────────────────────────────────────────────────────
MATCH (o:Ontology {name: "legal_demo"})
MERGE (contract:NodeType {name: "Contract"})
SET contract.description = "A binding agreement between parties"
MERGE (o)-[:CONTAINS]->(contract);

MATCH (contract:NodeType {name: "Contract"})
MERGE (contract)-[:HAS_PROPERTY]->(pd:PropertyDef {name: "title"})
SET pd.type = "STRING",
    pd.description = "Contract title or heading",
    pd.required = true,
    pd.is_key = true,
    pd.normalizer = "whitespace";

MATCH (contract:NodeType {name: "Contract"})
MATCH (am:AliasMap {name: "JURISDICTION_ALIASES"})
MERGE (contract)-[:HAS_PROPERTY]->(pd:PropertyDef {name: "jurisdiction"})
SET pd.type = "STRING",
    pd.description = "Governing jurisdiction",
    pd.normalizer = "alias_map"
MERGE (pd)-[:USES_ALIAS_MAP]->(am);

MATCH (contract:NodeType {name: "Contract"})
MERGE (contract)-[:HAS_PROPERTY]->(pd:PropertyDef {name: "signedDate"})
SET pd.type = "STRING",
    pd.description = "Date the contract was signed (YYYY-MM-DD)",
    pd.normalizer = "date";

MATCH (contract:NodeType {name: "Contract"})
MERGE (contract)-[:HAS_PROPERTY]->(pd:PropertyDef {name: "amount"})
SET pd.type = "FLOAT",
    pd.description = "Total contract value",
    pd.normalizer = "monetary_amount";

MATCH (contract:NodeType {name: "Contract"})
MERGE (contract)-[:HAS_PROPERTY]->(pd:PropertyDef {name: "caseNumber"})
SET pd.type = "STRING",
    pd.description = "Court case reference, normalized to dot-separated form",
    pd.normalizer = "regex_normalize",
    pd.regex_pattern = "[_\\-\\s]+",
    pd.regex_replacement = ".";

MATCH (contract:NodeType {name: "Contract"})
MERGE (contract)-[:HAS_PROPERTY]->(pd:PropertyDef {name: "contractType"})
SET pd.type = "STRING",
    pd.description = "Type of contract — must be one of the enumerated values",
    pd.normalizer = "enum_validate",
    pd.enum_values = ["service", "supply", "employment", "licensing", "settlement"];

// ── NodeType: Penalty ───────────────────────────────────────────────────────
MATCH (o:Ontology {name: "legal_demo"})
MERGE (penalty:NodeType {name: "Penalty"})
SET penalty.description = "A monetary penalty arising from contract breach"
MERGE (o)-[:CONTAINS]->(penalty);

MATCH (penalty:NodeType {name: "Penalty"})
MERGE (penalty)-[:HAS_PROPERTY]->(pd:PropertyDef {name: "name"})
SET pd.type = "STRING",
    pd.description = "Penalty description (auto-composed if missing)",
    pd.required = true,
    pd.is_key = true,
    pd.normalizer = "compose_name_from_fields",
    pd.name_template = "{currency} {amount} penalty";

MATCH (penalty:NodeType {name: "Penalty"})
MERGE (penalty)-[:HAS_PROPERTY]->(pd:PropertyDef {name: "amount"})
SET pd.type = "FLOAT",
    pd.description = "Penalty amount",
    pd.normalizer = "monetary_amount";

MATCH (penalty:NodeType {name: "Penalty"})
MERGE (penalty)-[:HAS_PROPERTY]->(pd:PropertyDef {name: "currency"})
SET pd.type = "STRING",
    pd.description = "ISO 4217 currency code",
    pd.normalizer = "currency";

// ── RelationshipType: PARTY_TO (Party -> Contract) with `role` property ─────
MATCH (o:Ontology {name: "legal_demo"})
MATCH (party:NodeType {name: "Party"})
MATCH (contract:NodeType {name: "Contract"})
MERGE (rt:RelationshipType {name: "PARTY_TO"})
SET rt.description = "Connects a Party to a Contract they are bound by"
MERGE (o)-[:CONTAINS]->(rt)
MERGE (rt)-[:FROM]->(party)
MERGE (rt)-[:TO]->(contract);

MATCH (rt:RelationshipType {name: "PARTY_TO"})
MERGE (rt)-[:HAS_PROPERTY]->(pd:PropertyDef {name: "role"})
SET pd.type = "STRING",
    pd.description = "Role in the contract (e.g. 'buyer', 'seller', 'plaintiff')",
    pd.normalizer = "lowercase";

// ── RelationshipType: RESULTS_IN (Contract -> Penalty) ──────────────────────
MATCH (o:Ontology {name: "legal_demo"})
MATCH (contract:NodeType {name: "Contract"})
MATCH (penalty:NodeType {name: "Penalty"})
MERGE (rt:RelationshipType {name: "RESULTS_IN"})
SET rt.description = "A breach of this contract resulted in this penalty"
MERGE (o)-[:CONTAINS]->(rt)
MERGE (rt)-[:FROM]->(contract)
MERGE (rt)-[:TO]->(penalty);
