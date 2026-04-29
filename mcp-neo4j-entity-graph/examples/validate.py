"""Standalone end-to-end validation for the ontology-as-graph flow.

Connects to a real Neo4j instance using .env credentials, sets up the Ontology
DB constraints, loads the example legal ontology, generates the Pydantic schema,
and runs validator smoke tests on the generated code.

Run from the `mcp-neo4j-entity-graph/` package root:

    uv run python examples/validate.py

Requires .env at the workspace root with:
    NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
    NEO4J_DATABASE (default: "neo4j" — used for documents)
    NEO4J_ONTOLOGY_DATABASE (default: "ontology")

Note: this script does NOT exercise the LLM extraction path (extract_entities).
For that, use the MCP tool flow with sample PDFs after this script passes.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import AsyncGraphDatabase
from platformdirs import user_cache_dir

from mcp_neo4j_entity_graph.ontology_loader import load_ontology
from mcp_neo4j_entity_graph.schema_generator import generate_extraction_models_code


CYPHER_FILE = Path(__file__).parent / "legal_ontology.cypher"


SETUP_STATEMENTS = [
    "CREATE CONSTRAINT ontology_name_unique IF NOT EXISTS FOR (o:Ontology) REQUIRE o.name IS UNIQUE",
    "CREATE CONSTRAINT node_type_name_unique IF NOT EXISTS FOR (nt:NodeType) REQUIRE nt.name IS UNIQUE",
    "CREATE CONSTRAINT relationship_type_name_unique IF NOT EXISTS FOR (rt:RelationshipType) REQUIRE rt.name IS UNIQUE",
    "CREATE CONSTRAINT alias_map_name_unique IF NOT EXISTS FOR (am:AliasMap) REQUIRE am.name IS UNIQUE",
    "CREATE CONSTRAINT blocklist_name_unique IF NOT EXISTS FOR (bl:Blocklist) REQUIRE bl.name IS UNIQUE",
    "CREATE INDEX property_def_name IF NOT EXISTS FOR (pd:PropertyDef) ON (pd.name)",
]


async def main():
    load_dotenv()
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    username = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password")
    ontology_db = os.environ.get("NEO4J_ONTOLOGY_DATABASE", "ontology")

    print(f"Connecting to {uri} as {username}, ontology DB = {ontology_db}")
    driver = AsyncGraphDatabase.driver(uri, auth=(username, password))

    try:
        # ── Step 1: setup constraints ────────────────────────────────────
        print("\n[1/4] Setting up Ontology DB constraints...")
        async with driver.session(database=ontology_db) as session:
            for stmt in SETUP_STATEMENTS:
                await session.run(stmt)
        print(f"      OK — {len(SETUP_STATEMENTS)} constraints/indexes ensured")

        # ── Step 2: load example ontology ───────────────────────────────
        print(f"\n[2/4] Loading example ontology from {CYPHER_FILE.name}...")
        cypher_text = CYPHER_FILE.read_text()
        # Strip `//` line comments first, then split on `;\n` boundaries.
        # The example file's statements are independent so each split chunk
        # is a self-contained transaction.
        no_comments = "\n".join(
            ln for ln in cypher_text.splitlines() if not ln.lstrip().startswith("//")
        )
        statements = [s.strip() for s in no_comments.split(";\n") if s.strip()]
        executed = 0
        async with driver.session(database=ontology_db) as session:
            for stmt in statements:
                result = await session.run(stmt)
                await result.consume()
                executed += 1
        print(f"      OK — executed {executed} cypher statement(s)")

        # ── Step 3: generate Pydantic schema ────────────────────────────
        print("\n[3/4] Generating Pydantic schema from 'legal_demo'...")
        schema, normalizers = await load_ontology(driver, ontology_db, "legal_demo")
        code = generate_extraction_models_code(schema, normalizers)

        cache_root = Path(user_cache_dir("mcp-neo4j-entity-graph")) / "schemas"
        cache_root.mkdir(parents=True, exist_ok=True)
        out_path = cache_root / "legal_demo.py"
        out_path.write_text(code)
        print(f"      OK — wrote {len(code)} chars to {out_path}")
        print(f"           {len(schema.entity_types)} entity types, "
              f"{len(schema.relationship_types)} relationship types, "
              f"{len(normalizers)} normalizer configs")

        # ── Step 4: smoke-test the generated module ─────────────────────
        print("\n[4/4] Smoke-testing generated validators...")
        spec = importlib.util.spec_from_file_location("extraction_models", out_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["extraction_models"] = mod
        spec.loader.exec_module(mod)

        checks: list[tuple[str, bool, str]] = []

        # Generic: whitespace
        c = mod.ContractEntity(title="  My Contract  ")
        checks.append(("Contract.title whitespace", c.title == "My Contract", repr(c.title)))

        # Alias map
        c2 = mod.ContractEntity(title="X", jurisdiction="NY")
        checks.append(("Contract.jurisdiction alias_map", c2.jurisdiction == "New York", repr(c2.jurisdiction)))

        # Date
        c3 = mod.ContractEntity(title="X", signedDate="March 15, 2025")
        checks.append(("Contract.signedDate date", c3.signedDate == "2025-03-15", repr(c3.signedDate)))

        # Monetary
        c4 = mod.ContractEntity(title="X", amount="€1.5 billion")
        checks.append(("Contract.amount monetary_amount", c4.amount == 1_500_000_000.0, repr(c4.amount)))

        # Regex normalize
        c5 = mod.ContractEntity(title="X", caseNumber="2024-CV-001")
        checks.append(("Contract.caseNumber regex_normalize", c5.caseNumber == "2024.CV.001", repr(c5.caseNumber)))

        # Enum validate (pass)
        c6 = mod.ContractEntity(title="X", contractType="service")
        checks.append(("Contract.contractType enum (valid)", c6.contractType == "service", repr(c6.contractType)))

        # Enum validate (skip)
        c7 = mod.ContractEntity(title="X", contractType="weird")
        checks.append(("Contract.contractType enum (skip)", c7.contractType == "__SKIP__", repr(c7.contractType)))

        # Blocklist
        p = mod.PartyEntity(name="the parties")
        checks.append(("Party.name blocklist", p.name == "__SKIP__", repr(p.name)))
        p2 = mod.PartyEntity(name="Acme Inc")
        checks.append(("Party.name normal", p2.name == "Acme Inc", repr(p2.name)))

        # compose_name_from_fields
        pen = mod.PenaltyEntity(amount="$500K", currency="dollar")
        checks.append(("Penalty compose_name", pen.name == "USD 500000.0 penalty", repr(pen.name)))
        pen2 = mod.PenaltyEntity(name="Custom Name", amount=100, currency="USD")
        checks.append(("Penalty preserve name", pen2.name == "Custom Name", repr(pen2.name)))

        passed = sum(1 for _, ok, _ in checks if ok)
        for label, ok, value in checks:
            sym = "✓" if ok else "✗"
            print(f"      {sym} {label}: {value}")
        print(f"\n      {passed}/{len(checks)} checks passed")

        if passed != len(checks):
            print("\n  ✗ VALIDATION FAILED — see failed checks above")
            return 1

        print("\n  ✓ ALL VALIDATION CHECKS PASSED")
        print(f"\n     Schema cached at: {out_path}")
        print( "     Next: ingest a PDF and call extract_entities(ontology_name='legal_demo')")
        return 0

    finally:
        await driver.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
