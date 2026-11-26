# Restricted-user embedding onboarding — 2026-11-24

Scope: verify actual Neo4j authorization before embedding-provider work, without
workspace data or provider API calls. This replaces the earlier mocked privilege
failure as the onboarding evidence; it does not replace the identity/race tests.

## Environment and isolation

- Neo4j **2025.12.1 Enterprise**, disposable local Docker DBMS.
- Each test creates its own UUID database, custom role and fresh user. Administrator
  access provisions and removes these fixtures only; `embed_chunks` runs through the
  fresh user's own driver and MCP client.
- The custom role has database access, graph `MATCH`/`WRITE`, name management and
  create/show-index permissions. Constraint privileges vary per case below.
- Provider execution is replaced with deterministic three-dimensional vectors and a
  call counter. Neo4j authentication, privilege enforcement, index/constraint creation
  and vector publication are real. No OpenAI/provider credentials are used.

## Results

Final validation: **4 real-authorization integration tests passed**, plus **5 embedding
identity unit tests passed** after the wording change. Cleanup verification found zero
remaining test databases, users or roles with this test suite's prefixes.

| Fresh runtime role / constraint state | Observed result | Provider calls | Vector writes |
| --- | --- | --- | --- |
| `SHOW CONSTRAINT`, no `CREATE CONSTRAINT`; constraint absent | Native `Security.Forbidden` for `create_constraint`; actionable MCP error | 0 | 0 |
| Same role; exact constraint precreated by administrator | Embedding succeeds | 1 deterministic stub call | 1 |
| `CREATE CONSTRAINT` granted; `SHOW CONSTRAINT` explicitly denied | Native `Security.Forbidden` for showing constraints; actionable MCP error | 0 | 0 |
| `CREATE CONSTRAINT` and `SHOW CONSTRAINT` granted; fresh database | Embedding succeeds; identity metadata stored; no temporary lock remains | 1 deterministic stub call | 1 |

The precreated case matters: on this tested server, `CREATE CONSTRAINT ... IF NOT
EXISTS` succeeds without creation privilege when the matching named constraint
already exists. Requiring every runtime role to receive `CREATE CONSTRAINT` would
therefore overstate the requirement. Runtime inspection still needs `SHOW CONSTRAINT`.

Both denial cases explicitly verify an absent vector and input hash, in addition to
the zero provider-call counter. Successful publication verifies three dimensions and
a 64-character input hash; temporary publication lock nodes are removed.

## Narrow onboarding fix

The existing error already preserved Neo4j's actual denial and stated that no provider
request or vector write occurred. Its remediation only said to check schema privileges.
The message now names `SHOW CONSTRAINT` and the two setup options: grant `CREATE
CONSTRAINT`, or have an administrator precreate the exact reserved constraint:

```cypher
CREATE CONSTRAINT neo4j_mcp_embedding_lock_unique IF NOT EXISTS
FOR (lock:EmbeddingPublicationLock) REQUIRE lock.indexName IS UNIQUE;
```

README and embedding permission notes now describe both options. Publication behavior,
privilege checks and defaults are unchanged. This is a database-role check, not evidence
that Aura Free categorically prohibits constraints. Neo4j documents constraint privileges
separately from graph writes: [database privileges](https://neo4j.com/docs/operations-manual/current/authentication-authorization/database-administration/),
[write privileges](https://neo4j.com/docs/operations-manual/current/authentication-authorization/privileges-writes/).

## Reproduction

Run only against an explicitly disposable Enterprise DBMS that supports native vectors
and Cypher 25, with administrator fixture credentials supplied in the environment:

```bash
NEO4J_MCP_RUN_EMBEDDING_PRIVILEGES=1 \
LITELLM_LOCAL_MODEL_COST_MAP=True \
mcp-neo4j-lexical-graph/.venv/bin/python -m unittest discover \
  -s tests/integration -p test_embedding_privileges_mcp.py -v
```

The test requires `NEO4J_URI`, `NEO4J_USERNAME` and `NEO4J_PASSWORD` for that disposable
DBMS. Its opt-in flag is disabled by default. It drops only the exact databases,
users and roles created for the current UUID fixtures.

This is onboarding correctness evidence, not a cold-setup benchmark or a hosted Aura
role-policy test. No network embedding call is included in these tests.
