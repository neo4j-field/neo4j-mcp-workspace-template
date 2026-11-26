# PageIndex discovery refresh — 26 November 2026

GraphRAG now notifies connected MCP clients when external ingestion makes lexical
navigation available, and when removal makes it unavailable. Tools remain hidden
unless the database contains the topology needed to use them.

One server-lifespan observer checks capabilities every two seconds while subscribed
sessions exist. It shares the probe across clients and remembers each client's
advertised state. Unchanged capabilities produce no notification. Transient probe
failures retain that state and retry; failed client notification channels cannot
terminate the server. Explicit discovery and navigation calls still check current
capability. No labels, relationships or properties were added.

The public MCP acceptance test starts on an empty isolated database. A separate
Neo4j connection creates Document → Section → Element, without making another
GraphRAG call. The connected client receives `tools/list_changed`, re-lists and
sees all four navigation tools. External deletion produces another notification
and hides them again. The integration passed against disposable `refresh-tests`;
the user's active database and Claude Code session were untouched.

Validation: 33 GraphRAG unit tests plus four subtests passed, including two-client
notifications, transport failure isolation and recovery after a transient probe
error. The live external-write acceptance passed again after hardening.

Delivered on [draft PR #2](https://github.com/neo4j-field/mcp-neo4j-graphrag/pull/2),
commit `0867f08b8eba58c328e4699b1323fa9661aa6b10`; setup/proxy share the updated
immutable source pin. Hosted unit and integration checks passed on this exact commit for Neo4j 5.26 Community and 2026.09 Community: [CI run](https://github.com/neo4j-field/mcp-neo4j-graphrag/actions/runs/45819947321).

Claude Code still needs to demonstrate that it honors the notification in a
long-lived session. Existing running processes retain their loaded code; this
change has not restarted or reconfigured the owner's active tests. Test the
empty-to-populated transition after loading the updated server, using a disposable
POC database. A one-time reload to load changed code is distinct from requiring a
reconnect after each ingestion.
