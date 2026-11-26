#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

PROJECTS=(
    mcp-neo4j-ingest
    mcp-neo4j-lexical-graph
    mcp-neo4j-entity-graph
    mcp-neo4j-proxy
)

for project in "${PROJECTS[@]}"; do
    project_dir="$ROOT_DIR/$project"
    printf '==> Build %s\n' "$project"
    uv --directory "$project_dir" build

    if [[ -d "$project_dir/tests" ]]; then
        printf '==> Test %s\n' "$project"
        uv --directory "$project_dir" run --frozen --with pytest pytest
    else
        printf 'SKIP %s tests: no tests/ directory present.\n' "$project"
    fi
done

printf '==> Test root ingest compiler and null handling\n'
uv run --project "$ROOT_DIR/mcp-neo4j-ingest" --frozen python -m unittest \
    tests.unit.test_ingest_query_compiler \
    tests.unit.test_ingest_csv_nulls -v

printf '==> Test workflow report validation\n'
uv run --project "$ROOT_DIR/mcp-neo4j-proxy" --frozen python -m unittest \
    tests.report_validation.test_report_validator -v

printf '==> Test safe setup dotenv handling\n'
python3 -m unittest tests.unit.test_setup_env -v

printf 'Verification completed; explicit skips above are not test passes.\n'
