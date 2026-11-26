#!/usr/bin/env bash
# Sourced by setup.sh; takes explicit paths so tests use disposable local remotes.
ensure_graphrag_checkout() {
  local checkout_dir="$1" pin_file="$2"
  local repository="${3:-https://github.com/neo4j-field/mcp-neo4j-graphrag}"
  local revision current status_line dirty=false fresh=false
  if ! command -v git >/dev/null 2>&1; then
    error "git is required to prepare mcp-neo4j-graphrag."
    return 1
  fi
  if [ ! -f "$pin_file" ]; then
    error "GraphRAG revision file missing: $pin_file"
    return 1
  fi
  revision="$(cat "$pin_file")"
  if ! [[ "$revision" =~ ^[0-9a-f]{40}$ ]]; then
    error "GraphRAG revision must be one full lowercase Git commit SHA: $pin_file"
    return 1
  fi
  if [ ! -e "$checkout_dir" ]; then
    info "Cloning GraphRAG at pinned revision $revision"
    git clone --no-checkout --depth 1 "$repository" "$checkout_dir" --quiet || return $?
    fresh=true
  elif [ ! -e "$checkout_dir/.git" ]; then
    error "GraphRAG directory is not a Git checkout: $checkout_dir. Move it aside and re-run setup; files were preserved."
    return 1
  fi
  current="$(git -C "$checkout_dir" rev-parse HEAD)" || return $?
  if [ "$current" = "$revision" ] && [ "$fresh" = false ]; then
    success "GraphRAG already at pinned revision $revision; local edits preserved"
    return 0
  fi
  if [ "$fresh" = false ]; then
    # uv may create this one untracked file. All other visible edits block updates.
    while IFS= read -r status_line; do
      [ "$status_line" = '?? .python-version' ] || dirty=true
    done < <(git -C "$checkout_dir" status --porcelain --untracked-files=all)
    if [ "$dirty" = true ]; then
      error "GraphRAG has local changes at a different revision. Commit/stash them or move the checkout aside, then re-run setup: $checkout_dir. Nothing was discarded."
      return 1
    fi
  fi
  if ! git -C "$checkout_dir" cat-file -e "$revision^{commit}" 2>/dev/null; then
    if ! git -C "$checkout_dir" fetch --depth 1 origin "$revision"; then
      error "Cannot fetch pinned GraphRAG revision $revision. Check network/origin access and re-run setup; checkout files were preserved."
      return 1
    fi
  fi
  # Do not overwrite ignored user configuration when changing revisions either.
  if ! git -C "$checkout_dir" checkout --detach --no-overwrite-ignore "$revision" --quiet; then
    error "Could not switch GraphRAG to $revision. Resolve conflicting local files and re-run setup; no force checkout was attempted."
    return 1
  fi
  # Retain the existing Python baseline without replacing user configuration.
  if [ ! -e "$checkout_dir/.python-version" ]; then
    printf '3.12\n' > "$checkout_dir/.python-version"
  fi
  success "GraphRAG ready at pinned revision $revision"
}
