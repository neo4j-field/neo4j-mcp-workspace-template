# Contributing

This repository is maintained solo. Keep changes small and reviewable.

## Routine fixes

1. Branch from the current release branch (currently `release/stabilization-2026-11`).
2. Make the change. Add or update tests when the server has a `tests/` directory.
3. Run `./scripts/verify-pr.sh`.
4. Open a PR with the short template.
5. Wait for the `PR / verify` check.
6. Review the diff and merge manually.

For small fixes, passing CI plus a quick diff review is enough.

## Larger or risky changes

A short design section in the PR is required before implementation when a change
touches any of these:

- database schema or data migration
- dependencies or package versions
- security or credentials
- publishing or release artifacts
- behavior across multiple servers

The design section should state the problem, intended behavior, main tradeoff,
test and manual-acceptance plan, and rollback. JM performs manual acceptance for
these changes.

## Rules

- Never commit `.env`, generated MCP configs, customer data, local outputs,
  credentials, or build artifacts.
- Each server owns its `pyproject.toml` and `uv.lock`. Do not run `uv sync` at
  the workspace root.
- Do not change model defaults, package versions, published artifacts, or
  release scope without explicit approval.
- No auto-merge. JM approves and merges.
