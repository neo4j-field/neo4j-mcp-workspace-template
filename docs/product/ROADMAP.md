# Roadmap

Build an approachable SE POC tool and readable reference implementation. Keep tested
correctness fixes; do not make production pipeline architecture a prerequisite for
shipping useful features. The owner has selected **N1 and N4 before release**.

## 1. Release commitments

Implement N1 native Docling heading hierarchy and N4 Ontology Graph Spec support in
parallel where files/contracts allow. Validate their integration before the final
combined CSV+PDF smoke. Keep commits reviewable; do not rewrite existing history.

Close the remaining narrow lexical deletion/metadata bugs (SEC-001, WRITE-004) and
verify EXT-003 against existing provenance instead of rebuilding it. Align Desktop
versions (DESK-001), measure clean setup including Docling, document reset/rebuild
and parser selection, and capture the synthetic 10k CSV + 50-page PDF baseline.

The [finite release checklist](RELEASE_CHECKLIST.md) defines evidence required to
ship. Local tests are useful evidence, not a substitute for hosted final-revision
CI, clean-clone setup, combined live E2E and aligned package smoke.

Before release, complete **SE-003**: tidy the repository, verify and remove unused
files, tools and code (including superseded capabilities), and propose improvements that help SEs find their way and locate reusable
code. Review documentation for freshness, accuracy and appropriate depth for both
humans and coding agents; align onboarding, the code map, AGENTS.md and skills.
Preserve useful history and user data. This scoped cleanup does not reopen the
deferred architecture work. Validate N1 coverage before release and, by default,
retire the older `assign_section_hierarchy` tool if redundant (SURF-004); record any
remaining use case before deciding.
Also investigate Docling section-extraction quality before release (LEX-004): use
controlled layout variants and an explicit hierarchy oracle, preserve benchmark
baselines, and distinguish native classification from adapter/graph mapping errors.

## 2. Next SE experience improvements

Prioritize demonstrated friction: credential-file setup handling, early model
preflight, advertised Desktop provider configuration and noisy diagnostics.
Document version/index behavior needs narrow user-visible fixes when reproduced,
not a general resumability framework. Retire the experimental parser surface in a
separate reviewable change; retain PyMuPDF, Docling and page-image.

## 3. Feature pipeline

After N1/N4 and release verification, prioritize [owner candidates](FEATURE_CANDIDATES.md#owner-additions--2026-11-24)
N2/N3/N5/N6 and graph-quality/multi-format work by SE value. These remain ideas,
not automatic commitments. Reuse existing replacement/provenance capabilities.

## 4. Deferred architecture

Defer general checkpointing, queue/backpressure redesign, large-scale CSV streaming,
external image storage, full historical provenance, cross-server run ledgers,
registry services and broad deduplication/refactoring. Reopen only with evidence
that the reference POC workload or an actual SE use case is blocked.

MCPB migration is deferred for scope; existing DXT compatibility does not remove
the obligation to ship version-aligned Desktop artifacts. AIP/hooks remain experiments.

[Backlog and preserved evidence](BACKLOG.md) · [Simplification decisions](reviews/2026-11-24-se-simplification.md)
