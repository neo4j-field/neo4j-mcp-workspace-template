# SE usability follow-up — 2026-11-24

Timeboxed initial read-only review of the README, setup entry point, shared graph
skill, document workflow, Docling workflow, chatbot retrieval guide and ontology
import/export documentation. This is a document/task walkthrough by a coding
agent, **not a timed novice-SE or Claude Code acceptance session**. No graph calls,
provider requests, setup reruns or user credentials were used in this review.
Setup safety/preflight and atomic replacement are concurrently being implemented;
their final behavior needs their own checks, not an inference from this snapshot.

## Simplification decisions realized

- Quick Start has one setup entry point, direct MCP readiness checks and measured
  Docling setup/first-use costs near the top.
- One visible parser table routes new document extensions automatically, distinguishes
  text/layout/visual PDF cases, and links detailed mode guides.
- Docling's native hierarchy is the happy path; hierarchy LLM correction is optional.
- README exposes a scoped extraction rebuild example and a fresh disposable-database
  alternative, with an explicit warning that namespaces do not isolate merge keys.
- PageIndex discovery/outline/content order, conditional visibility and flat-document
  fallback are explained. Ontology context is distinguished from physical schema.
- Experimental VLM-block mode no longer appears in live guides or tool schema.
  Historical planning evidence remains intentionally traceable.

## Concrete remaining friction

| Priority | Finding | Small next action |
|---|---|---|
| Before manual ontology QA | Shared `SKILL.md` steps 5–6 teach only `convert_schema` → Python schema. The spec import/extract/export route exists in entity README but is absent from this decision point. An agent following the main skill can miss the owner-selected ontology-file path. | Add one short alternative and link to the existing ontology import/export instructions. Keep `schema=` explicitly Python-only; arbitrary Python-schema export is not implemented. |
| Before final workflow review | The simplification decision to move detailed mechanics to Internals is only partially realized. Step 6 still embeds ownership withdrawal, legacy ownership migration and atomic publication mechanics in the default checklist. | Keep conflict policy and rebuild scope visible, move ownership implementation detail behind one advanced/reference link. No runtime rewrite. |
| Before final workflow review | Step 5 always asks the user to confirm normalization validators, even if the CSV key policy was already agreed and passed explicitly. It also shows unconditional lowercase sample code despite a case-preserving default. | Reuse already confirmed policy; ask only when source identity is ambiguous or the policy changes. Keep case-sensitive identifier guidance near the sample. |
| Small documentation fix | Skill preflight says "read `.env`" broadly, while AGENTS forbids reading passwords. The intended operation is selecting two nonsecret model variables. | State selective parsing of only model/provider configuration, without printing credentials or the entire file. |
| Small documentation fix | Main skill report flag says add `--pdf-data-present` only for PDFs; DOCUMENT_MODE correctly says use this legacy flag for any document extraction. Chatbot report examples also still say CSV/PDF and omit source anchors. | Align shared report wording with document workflow and cite null pages/source anchors for pageless content. |
| Manual SE check | Conditional tool discovery may depend on the coding client's tool-list refresh. Docs mention this, but that does not prove Claude Code notices a tool after ingestion in the same session. | Keep QA-001's hidden → visible PageIndex test as an explicit human-client acceptance test. |

These are finite documentation/acceptance improvements, not reasons to reopen the
completed correctness safeguards or add orchestration infrastructure. Desktop
version alignment, release smoke and benchmark dataset remain separate tasks.

## Evidence and limits

Fresh removal verification executed here: **31 unit/contract tests passed**,
including live in-process MCP tool-schema inspection and rejection of the removed
mode before DB access; retained document parsers and PDF contracts were exercised.
The graph skill passes its structural validator. No obvious removal regression was
found in those checks. Existing real-provider format acceptance (31 checks) and
CSV/PDF acceptance provide separate evidence; they were not rerun as a usability
study. QA-001 remains pending and must not be marked complete by this review.

The earlier [simplification agent](2026-11-24-se-simplification.md) finished its
planning decision list. The [cold setup review](2026-11-24-cold-setup.md) completed
measured setup checks. Neither constitutes a finished end-user usability test.

## Narrow documentation follow-up completed

The first five documentation findings above are now addressed:

- Main skill step 5 offers data-model-to-Python or spec-file import to Ontology DB,
  followed by schema generation and `ontology_name` extraction. It links existing
  import/export details and explicitly makes no arbitrary Pydantic export claim.
- Common extraction steps retain policy, scope and actionable failures. Detailed
  ownership withdrawal/publication/legacy safeguards moved intact into the linked
  `EXTRACTION_INTERNALS.md` reference.
- Generated normalization is checked against the agreed source-key policy. The
  default example preserves case; re-confirmation is limited to ambiguity/change.
- Model preflight instructs selective access to nonsecret settings and forbids
  whole-file output or reading/printing passwords/API keys.
- Shared report guidance applies the legacy `--pdf-data-present` flag to all
  document extraction. Chatbot examples now use format/source anchors for pageless
  documents and retain PDF page citations.

Validation after these documentation edits: **10 workflow/CI contracts passed**,
shared skill structural validation passed, local reference targets resolve, and
`git diff --check` passed. Runtime behavior was not changed. Conditional discovery
in the actual client, arbitrary-schema export acceptance and the remaining user
QA-001 scenarios stay pending. Setup preflight implementation and final release
packaging remain outside this documentation follow-up.
