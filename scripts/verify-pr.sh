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

printf 'Verification completed; explicit skips above are not test passes.\n'
