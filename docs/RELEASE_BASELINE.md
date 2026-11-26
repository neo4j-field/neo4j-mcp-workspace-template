# Release baseline

Date: 2026-11-26

This records provenance for the clean release line. It does not change versions,
source, artifacts, or publication state.

## Workspace baseline

The clean release branch starts at `9ed5a3be1ba946bf4f9f1a0adb26d99c78e6016f`
(`9ed5a3b`). At that revision:

- `mcp-neo4j-ingest` is version **0.1.0**.
- `mcp-neo4j-lexical-graph` is version **0.2.1**.
- `mcp-neo4j-entity-graph` is version **0.4.1**.
- `mcp-neo4j-proxy` is version **0.2.1**.

## Component notes

- The ingest tag `mcp-neo4j-ingest-v0.1.1` points at
  `51476ff5f5e713026c89769a00267153aa67fe30`, but the published PyPI package
  and `pyproject.toml` version are **0.1.0**.
- Proxy `0.2.1` was published from `c76ae8af59e44c21b71704f8fa0605a40aa3c275`.
  Later source has a skill-packaging difference from that tag.
- GraphRAG is a separate repository. Its `v0.4.2` release is
  `19ed03d5cd4f889a58bd4fe35dc66bb64854f7d8`.

## Claude Desktop

The published Desktop asset contains internal DXT version **0.1.1**, invokes
proxy **0.2.1**, and defaults extraction to `openai/gpt-5-mini`. Current source
declares `openai/gpt-5.4-mini`. Do not change either default without approval.

## Rule

Do not infer package contents from tag names alone. Version, dependency, DXT, and
published-artifact changes require separate verification.
