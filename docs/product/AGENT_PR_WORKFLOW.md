# Agent-assisted PR workflow

Status: approved working process; bootstrap tasks below must be completed before using the flow for implementation.  
Owner: JM  
Execution environment: Claude Code  
Applies to: `neo4j-mcp-workspace-template` and the separate `mcp-neo4j-graphrag` repository

Related scope audit: [2026-11-26 release-scope audit](reviews/2026-11-26-release-scope-audit.md)

## 1. Objective and non-negotiables

Automate design drafting, implementation, testing, review, and evidence preparation while preserving human understanding and control.

The required sequence is:

> **Agent design → JM approves design → automated implementation/tests/review → JM walkthrough and manual acceptance → fixes if needed → JM approves merge.**

Non-negotiables:

- JM approves every design before implementation starts.
- JM manually understands and tests every PR, even when all automated checks pass.
- The implementation agent and review agent are different agents with separate contexts.
- No agent approves its own work or merges a PR.
- No auto-merge.
- Every PR includes code, tests, docs, and manual acceptance instructions for one coherent change.
- A material deviation from the approved design returns the PR to design review.
- Green tests are evidence, not proof of complete functional correctness or release readiness.

## 2. Current release-scope decisions

The detailed rationale and C01-C28 matrix live in the linked audit. Current decisions:

### Include after isolation, review, and testing

- Stabilization/correctness fixes, separated from larger architectures.
- N1 / C15: native Docling hierarchy.
- N4 / C19+C21: bounded ontology interchange and Python-schema export.
- C16: Markdown, TXT, local HTML/XHTML, and DOCX support.
- Claude Desktop, with coordinated packages, proxy pins, DXT, and exact-artifact tests.
- A separate GraphRAG patch release containing only approved C12 search/index fixes.

### Exclude

- C05+C06: extraction runs, claims, source-scoped ownership, and their persisted schema.
- C13: embedding identity/cache/publication locks and their persisted schema.
- C17+C18: PageIndex and refresh middleware; PageIndex was an unvalidated experiment.
- `assign_section_hierarchy`: remove implementation, skills, docs, and tests together.
- The `gpt-6-luna` default change unless separately approved; retain the previous model default.

### Open design decision

C20 ontology-retrieval context must be discussed jointly with N4 before approval. Decide:

- Ontology source of truth
- File-backed versus ontology-DB behavior and precedence
- Supported Ontology Graph Spec semantics
- Relationship to N4-produced artifacts
- Reload behavior after configuration/path changes
- Optional and unconfigured UX
- Declared ontology versus realized physical schema
- Implementation and release boundary in the separate GraphRAG repository

### Cross-feature requirements

- Test N1 behavior across applicable C16 formats: hierarchy, heading paths, chunking, citations, rebuilds, deletion, and pageless behavior.
- Document format-specific limitations, including unstyled DOCX and false Docling headings.
- Keep GraphRAG source in its own repository; never vendor it into the workspace.
- Preserve excluded implementations on an experiment/archive branch for possible later use.

## 3. Repository and branch model

Use the existing repositories. Do not create a replacement workspace repository.

### Workspace

- `main`: published/stable state; no direct implementation commits.
- `release/<release-name>`: clean integration branch from the agreed published baseline, reconciling component-specific release tags.
- `experiment/codex-full-2026-11-26` or equivalent: preserves the complete intentional mixed implementation as reference material.
- `fix/<short-name>`: one stabilization unit, targeting the release-integration branch.
- `feat/<short-name>`: one reviewed feature, targeting the release-integration branch.
- `chore/<short-name>`: process, CI, packaging, or release mechanics.

### GraphRAG

- Patch branch from the released baseline for approved C12 fixes only.
- Separate feature branch for C20 if its design is approved.
- Publish/tag the patch and consume it from the workspace as an external dependency.
- PageIndex, refresh middleware, and C20 are excluded from the stabilization patch.

### Parallel work

Use a separate git worktree for each builder agent/PR. Do not let multiple agents edit the same working tree. Plain worktrees plus PRs are sufficient; gbuild is optional for suitable features.

## 4. Roles

### Main Claude Code session — orchestrator

- Tracks workflow state and approved scope.
- Launches designer, builder, and reviewer agents.
- Ensures implementation does not start before JM's design approval.
- Records base/head SHAs and review evidence.
- Launches a fresh reviewer only after the builder stops at a fixed commit.
- Coordinates fixes and re-review.
- Never treats agent output as JM approval.
- Never merges without JM's explicit approval.

### Designer agent

- Produces a design note using the template.
- Inspects relevant code/history and identifies tradeoffs.
- Does not write implementation code.
- Defines non-goals, schema impact, tests, manual acceptance, and revert strategy.

### Builder agent

- Receives the approved design and acceptance criteria.
- Works only in its assigned branch/worktree.
- Implements with small coherent commits.
- Adds/updates tests, fixtures, docs, and manual acceptance instructions.
- Runs applicable local verification.
- Reports exact commands/results and any deviations.
- Does not launch/select its reviewer, resolve its own review findings, approve, or merge.

### Reviewer agent

- A fresh `general-purpose` agent, **not a fork** and not the builder.
- Does not inherit the builder's conversation or rationale.
- Initially receives only the approved design, base/head SHAs, acceptance criteria, and scope exclusions—not the builder's self-assessment.
- Has read/search tools and safe test execution, but no Edit/Write tools.
- Inspects the actual diff, code, tests, docs, and baseline behavior.
- Checks correctness, missing cases, scope creep, schema/tool-surface changes, and docs mismatch.
- Reports severity-ranked findings with `file:line` evidence.
- Can recommend approval or request changes, but cannot merge.

For follow-up fixes, the same independent reviewer may re-review to retain context. Use a new reviewer after a major redesign or when independence needs to be refreshed. Every new head SHA requires review of the changes and fresh CI.

## 5. Workflow states

### `design-draft`

Designer produces:

- Problem and evidence
- Current behavior and desired behavior
- Options and recommendation
- Non-goals/exclusions
- Schema, MCP tool, configuration, dependency, and documentation impact
- Implementation outline
- Automated test plan
- Manual acceptance scenario
- Revert strategy

**Gate:** JM explicitly approves. No implementation before this.

### `implementation`

Builder implements the approved design in an isolated worktree. A material behavior/scope/design deviation returns to `design-draft`.

### `automated-review`

At a fixed head SHA:

- Applicable local unit/contract tests run.
- Disposable-Neo4j integration tests run where relevant.
- GitHub CI runs on the committed revision.
- `stellar-review` runs.
- The independent reviewer inspects the diff.
- Scope checks verify excluded tools/schema/features are absent.

Builder addresses findings in new commits. Review and CI rerun as required.

### `manual-acceptance`

JM receives:

- Approved design and deviations
- Guided diff walkthrough
- Automated test and review evidence
- Exact manual steps and expected observations
- Known limitations and unverified areas

JM inspects and runs the manual acceptance personally, then records feedback or acceptance in the PR.

### `merge-ready`

Only after JM's acceptance and GitHub approval. No agent merges. New commits after acceptance require appropriate re-review/retesting and renewed approval.

## 6. PR contract

Every PR description contains:

1. Link to the approved design.
2. Problem and before → after behavior.
3. Non-goals and explicit exclusions.
4. Guided implementation walkthrough.
5. Schema, MCP tool, configuration, dependency, and docs impact.
6. Base and reviewed head SHAs.
7. Builder and independent reviewer identified separately.
8. Automated tests with exact commands/results.
9. `stellar-review` result and disposition of findings.
10. Manual acceptance steps using committed fixtures where possible.
11. JM's manual acceptance result/feedback.
12. Known limitations and unverified claims.
13. Revert/rollback implications.

Keep PRs small enough for JM to explain the change after a focused walkthrough. Split a PR when unrelated fixes or features make that impractical.

## 7. Automation and Oskar tools

### `stellar-review` — adopt for every implementation PR

- Quick local pass before marking a PR ready for review.
- Full pass before merge, locally or in CI.
- Calibrate against repository `AGENTS.md` rules.
- Treat findings as review evidence, not automatic truth.
- It supplements functional review and tests; it does not replace them.

### `gbuild` — pilot on N4 after the base workflow works

- Use its human-approved design gate, dependency planning, isolated worktrees, implementation, and fresh review.
- Pilot on N4 because it has a bounded contract and concrete acceptance artifacts.
- Do not initially use it to untangle C02-C07 stabilization history.
- It is Claude Code-led; Codex may provide additional independent review but is not the gbuild runner.
- JM still performs manual acceptance and merge approval.

### `product-skills` / `problem-first`

Use once during the N4/C20 design discussion if helpful to clarify the underlying problem before selecting a solution.

### `autoresearch`

Not part of the initial flow. Reserve for measured performance/benchmark work.

## 8. GitHub enforcement

Configure both repositories as applicable:

- Pull requests required for `main` and release-integration branches.
- Required CI status checks.
- One approving review from JM.
- Code Owner review through `CODEOWNERS`.
- Dismiss stale approvals after new commits.
- Require review conversations to be resolved.
- Block force pushes and direct bypass.
- Disable auto-merge.

GitHub enforces CI and human approval. Claude Code orchestration enforces design approval and builder/reviewer independence.

## 9. Testing policy

### Every PR

- Deterministic unit/contract tests.
- Applicable lint/type/package checks.
- Docs and skill consistency checks.
- Explicit scope/schema assertions where relevant.

### Database-affecting changes

- Disposable Neo4j integration tests.
- No valuable/shared database use.
- No claim that mocked providers establish extraction/model quality.

### Features

- N1: real-PDF MCP acceptance, clear/ambiguous headings, all affected chunkers, removal of the old hierarchy tool.
- N4: normative validation, semantic roundtrips, rollback/unsupported cases, real import → extraction → export, Python export tests in CI.
- C16: real fixtures for every supported format and mixed folders; N1 interactions and format-specific limitations.
- C20 if approved: real N4 artifact interoperability and declared-versus-realized schema behavior.

### Final release

- Hosted CI green on exact root and GraphRAG commits.
- Clean-clone setup.
- One live CSV+PDF end-to-end run on the final revision.
- Wheels built, inspected for resources, and installed in isolation.
- Rebuilt DXT installed through the real Desktop path with exact child versions/tools verified.
- Excluded PageIndex, run/claim, embedding-lock, and other deferred surfaces explicitly absent.

## 10. Final integrated release audit

After all intended PRs are merged into the release-integration branch and before tagging/publishing, run a separate release audit. This is distinct from per-PR review: it examines interactions, accumulated drift, and the actual delivery artifacts.

### Audit rules

- Freeze the candidate at an exact root commit and exact GraphRAG release/commit.
- Use fresh independent audit agents, not the builders of the changes being audited.
- Review the complete published-baseline → release-candidate diff, not only individual PR summaries.
- Run a full `stellar-review` pass over the integrated change set.
- Produce severity-ranked findings with `file:line` evidence; do not rewrite code during the audit without JM's approval.
- Fix findings through the normal design/build/review/manual-acceptance PR flow, then rerun affected checks and the final audit on the new candidate.
- Save the result as `docs/product/reviews/<date>-final-release-audit.md`.
- JM performs a final integrated manual walkthrough and explicitly approves tagging/publication.

### Code quality and best practices

- Dead/unused files, tools, registrations, parameters, branches, helpers, fixtures, and duplicate manifests.
- Unnecessary duplication, unclear boundaries, excessive abstraction, and accidental scope leftovers.
- Error handling, async/background-job behavior, transaction boundaries, cancellation, resource cleanup, and logging.
- Dependency/version/lock consistency and avoidance of unmaintained or unnecessary dependencies.
- Security/setup hygiene: no secrets, unsafe dotenv evaluation, unsafe defaults, or unintended remote/resource access.
- Project-specific fitness as readable reference code for quick prototypes/demos; do not impose production-platform machinery that does not serve that purpose.
- Explicit absence of excluded C05/C06, C13, C17+C18, and other deferred surfaces.

### Documentation and first-run UX

- README Quick Start works from a clean clone and lists all prerequisites in the right order.
- README, skills, `AGENTS.md`, `CLAUDE.md`, Desktop docs, package docs, examples, and release notes match actual tools/arguments/defaults.
- No stale `vlm_blocks`, `assign_section_hierarchy`, PageIndex, deferred ontology, or ownership/cache claims.
- Supported formats and N1/N4/C16 limitations are accurate and visible.
- Every documented command and acceptance example is executed or explicitly marked unverified.
- Error messages and recovery instructions cover expected first-run failures without manual surgery.

### Verification and artifacts

- Hosted CI green on the exact candidate; all intended suites included and referenced files tracked.
- Disposable-Neo4j integration tests and final live CSV+PDF E2E completed.
- N1/N4/C16 cross-feature acceptance completed, including applicable format interactions.
- Wheels inspected for required resources and installed in isolation.
- Proxy pins, package versions, locks, GraphRAG release, DXT manifest, and built DXT agree.
- Rebuilt DXT installed through the real Desktop path; exact child versions and tools verified.
- Saved evidence is reproducible from committed fixtures/scripts; ignored local-only reports are not treated as release proof.

### Release decision

The final audit ends with one of:

- **Approve for release:** no unresolved blockers; JM accepts any documented limitations.
- **Approve with follow-ups:** only explicitly non-blocking findings remain, each recorded with an owner/issue.
- **Hold release:** blockers return through the PR workflow and the corrected candidate is audited again.

## 11. Bootstrap TODO — complete before starting implementation flow

### Preserve and baseline

- [ ] Verify GitHub access, repository ownership, default branches, release tags, and the component-specific published baselines.
- [ ] Inventory the current working tree for intentional source/tests/docs versus credentials, generated configs, customer data, outputs, and stale artifacts.
- [ ] Commit and push the complete intentional current state to `experiment/codex-full-2026-11-26` (or agreed equivalent) for preservation only.
- [ ] Verify the archive branch contains all required untracked runtime/test resources and no secrets/private data.
- [ ] Create the clean `release/<release-name>` integration branch from the agreed published baseline; document component-tag reconciliation.
- [ ] Confirm the existing mixed `stabilization` branch will be used only as reference, not cleaned up through one large revert.

### Bootstrap the process

- [ ] Create `chore/pr-workflow` from the appropriate stable base.
- [ ] Add `CONTRIBUTING.md` describing this state machine and roles.
- [ ] Add `.github/pull_request_template.md` implementing the PR contract.
- [ ] Add `docs/process/DESIGN_TEMPLATE.md` and `docs/process/MANUAL_ACCEPTANCE_TEMPLATE.md`.
- [ ] Add `.claude/agents/pr-designer.md`, `pr-builder.md`, and `pr-reviewer.md` with the permissions/independence rules above.
- [ ] Add or document a standard local PR verification command; do not invent a repository-wide dependency/install step that conflicts with per-server `uv` projects.
- [ ] Add CI checks needed by the workflow and confirm their exact names for branch protection.
- [ ] Open the process-only PR `chore: add reviewed agent PR workflow`; JM manually reviews and merges this bootstrap PR.

### GitHub and review tooling

- [ ] Add/update `CODEOWNERS` with JM's actual GitHub account.
- [ ] Configure branch rulesets/protection and required checks after those checks exist.
- [ ] Verify agent credentials cannot bypass branch protection or merge without JM.
- [ ] Install/configure `stellar-review`; verify `git`, `gh`, `jq`, authentication, and local quick mode.
- [ ] Calibrate `stellar-review` against `AGENTS.md`; do not enable unrelated CI posting/deployment changes without approval.
- [ ] Decide whether the full `stellar-review` pass runs locally, in CI, or both.
- [ ] Defer gbuild installation/setup until the ordinary flow is proven; then pilot it on N4.

### Work intake and test infrastructure

- [ ] Create a GitHub release milestone and issues linked to the C01-C28 audit identifiers.
- [ ] Turn the stabilization fixes into a fix ledger: problem, impact, minimal correction, dependencies, schema effect, tests, docs, exclusions, and source location in the preserved implementation.
- [ ] Order stabilization PRs, beginning with independent low-coupling fixes; handle C03/C04 separation from C05/C06 deliberately.
- [ ] Define disposable Neo4j test-database provisioning and cleanup.
- [ ] Define which real-provider tests are manual/scheduled versus required per PR, including cost controls.
- [ ] Ensure fixtures and expected manual observations are committed; do not rely on gitignored local evidence.
- [ ] Add release-scope contract checks for excluded tools/schema/features.
- [ ] Define the exact clean-clone, wheel, DXT, and Desktop acceptance procedures.

### Dry run and start

- [ ] Run one tiny, low-risk PR through the complete flow to validate orchestration, independent review, CI, manual acceptance, and GitHub enforcement.
- [ ] Record any workflow gaps and update the process before starting the stabilization queue.
- [ ] Start stabilization implementation only after the dry run passes.
- [ ] Review N1/N4/C16 designs only on the stabilized base; hold C20 for its joint N4 design discussion.

## 12. Definition of done for every PR

A PR is done only when:

- Its approved design is implemented without unapproved scope changes.
- The independent reviewer has inspected the actual head revision.
- CI and applicable integration tests pass on that revision.
- Review findings are addressed or explicitly accepted by JM.
- Docs, skills, configuration, and tests agree with runtime behavior.
- JM has personally completed the walkthrough and manual acceptance.
- JM approves the merge.

## 13. Context handoff

At the time this document was written:

- The implementation and release-scope audits are complete; no release has been made.
- The current tree remains a mixed committed/uncommitted implementation and must be preserved before branch reconstruction.
- No stabilization/feature implementation under this workflow has started.
- The next action is the bootstrap TODO above, beginning with baseline verification and preservation.
- C20 is the remaining open feature-design decision.
