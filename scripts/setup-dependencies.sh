#!/usr/bin/env bash
# Sourced by setup.sh; kept separate so dependency setup can be tested without
# reading credentials or generating client configuration.

SETUP_SYNC_NAMES=()
SETUP_SYNC_SECONDS=()
SETUP_SYNC_STATES=()

sync_server() {
  local server_dir="$1"; shift
  local abs_dir="$WORKSPACE_DIR/$server_dir"
  if [ ! -d "$abs_dir" ]; then
    warn "$server_dir directory not found, skipping"
    return 0
  fi
  local env_state="project .venv absent"
  if [ -d "$abs_dir/.venv" ]; then
    env_state="project .venv present"
  fi
  local started_at="$SECONDS"
  local sync_status=0
  info "uv sync → $server_dir ($env_state; cache state not inferred)"
  if uv sync --directory "$abs_dir" "$@"; then
    sync_status=0
  else
    sync_status=$?
  fi
  local elapsed=$((SECONDS - started_at))
  SETUP_SYNC_NAMES+=("$server_dir")
  SETUP_SYNC_SECONDS+=("$elapsed")
  SETUP_SYNC_STATES+=("$env_state")
  if [ "$sync_status" -ne 0 ]; then
    error "$server_dir dependency sync failed after ${elapsed}s (exit $sync_status)"
    error "Run manually: uv sync --directory \"$abs_dir\" $*"
    return "$sync_status"
  fi
  success "$server_dir dependencies ready in ${elapsed}s ($env_state)"
}

report_dependency_timings() {
  info "Dependency sync elapsed times (whole seconds; 0s means under one second):"
  local index
  for ((index=0; index<${#SETUP_SYNC_NAMES[@]}; index++)); do
    info "  ${SETUP_SYNC_NAMES[$index]}: ${SETUP_SYNC_SECONDS[$index]}s — ${SETUP_SYNC_STATES[$index]}"
  done
  info "An existing .venv does not prove a warm cache; downloads and parser model assets can add time."
}

sync_local_servers() {
  sync_server mcp-neo4j-ingest || return $?

  info "Verifying neo4j-ingest imports..."
  if ! uv --directory "$WORKSPACE_DIR/mcp-neo4j-ingest" run python -c "import mcp_neo4j_ingest" 2>&1; then
    error "neo4j-ingest failed import check — check dependencies and server configuration"
    return 1
  fi
  success "neo4j-ingest import OK"

  # Docling is part of the supported parser baseline, including when an older
  # .env still contains INSTALL_DOCLING=false. Do not rewrite that user's file.
  sync_server mcp-neo4j-lexical-graph --extra docling || return $?
  sync_server mcp-neo4j-entity-graph || return $?
  sync_server mcp-neo4j-graphrag || return $?
  report_dependency_timings
}
