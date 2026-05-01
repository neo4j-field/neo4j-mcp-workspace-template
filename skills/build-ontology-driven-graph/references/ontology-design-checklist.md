# Ontology design checklist

Methodology for going from a use case + a folder of documents to a small, defensible, extraction-ready ontology — written to the Ontology DB. Adapted from the ontology-builder-assistant methodology (jbarrasa/goingmeta/session45) for our graph-as-ontology storage.

The principle: **a small, purpose-led, evidence-backed ontology beats a comprehensive one.** Every element you include costs you in extraction quality and user comprehension. Aggressive scoping is a feature, not a bug.

## The two gates

Every entity type, property, and relationship type must pass **both**:

1. **Requirement gate** — at least one competency question (from Phase 2) requires it. If no competency question needs it, exclude it. Mention the exclusion briefly to the user so they know it was considered.
2. **Evidence gate** — the documents actually contain it (or a generalization of it). Verify by sampling `:Chunk` nodes:
   ```cypher
   MATCH (c:Chunk) WHERE c.text CONTAINS $term RETURN c.text LIMIT 5
   ```
   If a competency question requires something the documents don't contain, tell the user honestly: "Your question 'X' would need [thing], but I can't find evidence of it in the documents — do you have a different source for it?"

If a candidate fails either gate, exclude it. Do not invent entities the documents don't support; do not include entities just because they appear in the documents but aren't needed by any question.

## Top-level grounding

Pick **3-5 mutually-disjoint top-level types** as the spine of the ontology. Every entity goes under exactly one of these. This prevents "is this a Person or an Author?" confusion later.

Pick a scheme that fits the domain. Examples:

- **Documents domain (legal, regulation, internal docs)**: Person, Organization, Document, Place, Event
- **HR / talent**: Person, Organization, Role, Skill, Event
- **Finance / contracts**: Party, Instrument, Place, Event, MonetaryAmount (if treated as an entity)
- **Science / research**: Person, Organization, Publication, Concept, Event

Tell the user what the top-level types are and why you picked them. One sentence: "I'm grounding this in Person / Organization / Document / Place — that covers your competency questions and matches what I see in the documents."

The top-level types are themselves NodeTypes in the Ontology DB. Subtypes go under them via the `description` (we don't model subclass hierarchy in v1 — see "Max depth 3" below).

## Max depth 3, prefer properties over subclasses

Deep taxonomies (Document → Contract → ServiceAgreement → MasterServiceAgreement) are extraction-hostile. The LLM gets confused about which level to extract at. Keep it shallow:

- **Depth 1**: top-level grounding type (Person, Document, ...)
- **Depth 2**: a concrete entity type the user cares about (Contract, Employee, Patent)
- **Depth 3** (only if essential): a meaningful subtype that has *different properties or relationships* than its parent (e.g. `Litigation` vs `Contract` because litigation has additional fields like `caseNumber`, `court`)

If the only reason to add a level is "more specific name", use a property instead:

> Bad: `Contract → ServiceAgreement → MasterServiceAgreement`
> Good: `Contract` with property `contractKind` (`enum_validate` of `["service_agreement", "master_service_agreement", "nda", ...]`)

Rule of thumb: if two candidate types share more than half their properties, they should be one type with a discriminator property.

## Property vs entity decision

The most common modeling question. Heuristics:

| Use a **property** when | Use an **entity** when |
|---|---|
| The value is a simple literal (a date, an amount, a name string) | The value is something users want to ask questions *about* (e.g. "show me everything related to this jurisdiction") |
| There are no other things attached to it | It has its own properties or relationships |
| You'd never need to count it independently | You'd want to count it / aggregate over it |
| Example: `Contract.signedDate` | Example: `Jurisdiction` as its own node, linked via `:GOVERNS` |

Showcase to the user: "If we make jurisdiction a property, you can filter by it. If we make it an entity, you can ask 'show me everything about this jurisdiction', traverse to all contracts, all parties, all related cases, etc. — much richer. The cost is a slightly more complex extraction. For your competency questions about jurisdiction, I'd lean entity."

## Aristotelian definitions

Every NodeType gets a clear definition in its `description` field. Use the form:

> "An X is a Y that Z."

Where Y is a more general concept (often the top-level grounding type) and Z is what makes X distinct.

Examples:

- "A **Contract** is a **Document** that binds two or more parties to obligations and is governed by a jurisdiction."
- "A **Party** is a **Person or Organization** that is a signatory to a contract."
- "A **Jurisdiction** is a **Place** under whose laws a contract is interpreted."

This forces clarity and helps the LLM extract the right thing. Generic descriptions like "A document" or "A legal thing" lead to extraction noise.

For RelationshipTypes, describe what the relationship means in business terms:

- "PARTY_TO connects a Party to a Contract they have signed."
- "GOVERNED_BY connects a Contract to the Jurisdiction whose laws apply."

## Naming

| Element | Convention | Example |
|---|---|---|
| `:NodeType.name` | PascalCase | `Contract`, `LegalPerson`, `MonetaryAmount` |
| `:PropertyDef.name` | camelCase | `signedDate`, `effectiveDate`, `contractKind` |
| `:RelationshipType.name` | SCREAMING_SNAKE_CASE | `PARTY_TO`, `GOVERNED_BY`, `EMPLOYED_BY` |
| `:AliasMap.name` / `:Blocklist.name` | UPPER_SNAKE_CASE | `JURISDICTION_ALIASES`, `PERSON_BLOCKLIST` |

Names should be concrete and operational. `LegalEntity` is OK; `Thing` is not. `governedByJurisdiction` (relationship-as-property name) is wrong — use a relationship type `GOVERNED_BY` instead.

## Reuse external vocabularies (carefully)

If the user mentions a standard vocabulary they want to align with (FIBO, schema.org, FOAF, ESCO, ...), reuse names where they fit your competency questions, but don't import wholesale. Three principles:

1. Borrow the *name* and *definition*; don't import the parent hierarchy.
2. Note the alignment in the description: "A Person (aligned with FOAF:Person) is a natural human being who appears in the documents."
3. Don't add elements just because the standard has them. Stay in scope.

If reuse would force a depth-4 hierarchy or conflict with the top-level grounding, skip it.

## After every batch of writes

Run the validator (`scripts/validate_ontology.cypher`) after each batch of additions. Fix any errors before continuing. Warnings (empty AliasMaps, empty Blocklists) are OK to leave until Phase 5 fills them in.

## Final review with the user

Before moving to Phase 4 (Bloom handoff), summarize the ontology in plain language:

> "Here's what we built:
>
> - **N entity types**: [list with one-line definitions]
> - **M relationship types**: [list with one-line meaning]
> - **K properties** total
>
> This covers all [number] of your competency questions. The ones I excluded because they didn't pass the gates: [brief list with reason]. Any questions before we look at it visually?"

This is the moment to catch missing things. After they confirm, proceed to Phase 4.

## Mental checklist before extraction

- [ ] Every NodeType has exactly one key property (`is_key=true`)
- [ ] Every RelationshipType has exactly one `:FROM` and one `:TO`
- [ ] All competency questions can be answered by traversing this ontology
- [ ] No NodeType has more than 6-8 properties (if more, consider splitting)
- [ ] Top-level types are mutually disjoint
- [ ] Validator returns zero errors
- [ ] `generate_schema_from_ontology` succeeds without errors

If any of these fail, fix before extracting — the cost of fixing later (re-extracting after a schema change) is much higher than fixing now.
