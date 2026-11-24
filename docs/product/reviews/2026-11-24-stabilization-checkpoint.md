# Stabilization checkpoint — 2026-11-24

This checkpoint preserves the current stabilization work on branch `stabilization`.
It is not a release readiness sign-off.

## Verification rerun

- 46 fast tests passed: workflow/CI contracts and golden scorer (13), lexical
  runtime contracts and unit tests (15), ingest compiler (4), entity extraction
  and golden schema (8), report validation (6).
- `git diff --check`, setup shell syntax, and Desktop manifest JSON checks passed.
- A credential-pattern scan of changed and new text files found no matches.
  Local `.env` and generated `.codex/config.toml` remain ignored.
- LiteLLM used its bundled model cost map because the remote map was unavailable.
- Live database integration, packaged Desktop smoke, and provider calls were not
  rerun for this checkpoint. Earlier evidence is recorded in the September 23 audit.

## Continue from here

1. Verify BUG-004 on the affected Neo4j version and BUG-005 with a live provider.
2. Review EXT-001 stale output after forced re-extraction and EXT-002 skip semantics.
3. Run the owner's fresh Claude Code extraction using current local servers and
   inspect coverage, relationships, provenance, vector index, and validated report.
4. Complete TEST-003 with reviewed expected facts, real extraction output, and a
   comparison baseline.
5. Before release, align Desktop package versions and assess DXT/MCPB packaging
   (DESK-003), then complete the outstanding stabilization release requirements.

See `BACKLOG.md`, `ROADMAP.md`, and `2026-09-23-stabilization-audit.md` for scope
and remaining correctness, safety, scaling, and packaging work.
