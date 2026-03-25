#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─────────────────────────────────────────────────────────────
# Colors
# ─────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
success() { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
error()   { echo -e "${RED}[error]${RESET} $*" >&2; }

echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║   neo4j-mcp-workspace-template  setup.sh    ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo ""

# ─────────────────────────────────────────────────────────────
# 1. Check uv
# ─────────────────────────────────────────────────────────────
if ! command -v uv &> /dev/null; then
  error "uv is not installed."
  echo ""
  echo "  Install uv with one of:"
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "    brew install uv"
  echo "    pip install uv"
  echo ""
  echo "  Full docs: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi
success "uv found: $(uv --version)"

# ─────────────────────────────────────────────────────────────
# 2. Create or skip .env
# ─────────────────────────────────────────────────────────────
ENV_FILE="$WORKSPACE_DIR/.env"

if [ -f "$ENV_FILE" ]; then
  info ".env already exists — skipping credential prompts. Delete it to re-run setup."
else
  echo ""
  echo -e "${BOLD}── Neo4j connection ──────────────────────────────${RESET}"
  echo "  (press Enter to accept the default shown in brackets)"
  echo ""

  read -r -p "  NEO4J_URI        [neo4j://localhost:7687]: " input_uri
  NEO4J_URI="${input_uri:-neo4j://localhost:7687}"

  read -r -p "  NEO4J_USERNAME   [neo4j]: " input_user
  NEO4J_USERNAME="${input_user:-neo4j}"

  read -r -s -p "  NEO4J_PASSWORD   (hidden): " NEO4J_PASSWORD
  echo ""
  if [ -z "$NEO4J_PASSWORD" ]; then
    error "NEO4J_PASSWORD cannot be empty."
    exit 1
  fi

  read -r -p "  NEO4J_DATABASE   [neo4j]: " input_db
  NEO4J_DATABASE="${input_db:-neo4j}"

  echo ""
  echo -e "${BOLD}── LLM API keys (for embeddings & entity extraction) ──${RESET}"
  echo "  Needed to use lexical-graph and entity-graph."
  echo ""

  read -r -s -p "  OPENAI_API_KEY   (hidden): " OPENAI_API_KEY
  echo ""

  echo ""
  echo -e "${BOLD}── Embedding & extraction models ────────────────────${RESET}"
  echo "  Examples: text-embedding-3-small, gpt-5-mini"
  echo ""

  read -r -p "  EMBEDDING_MODEL  [text-embedding-3-small]: " input_embed
  EMBEDDING_MODEL="${input_embed:-text-embedding-3-small}"

  read -r -p "  EXTRACTION_MODEL [gpt-5-mini]: " input_extract
  EXTRACTION_MODEL="${input_extract:-gpt-5-mini}"

  # Write .env
  cat > "$ENV_FILE" << EOF
# Neo4j connection
NEO4J_URI=${NEO4J_URI}
NEO4J_USERNAME=${NEO4J_USERNAME}
NEO4J_PASSWORD=${NEO4J_PASSWORD}
NEO4J_DATABASE=${NEO4J_DATABASE}

# OpenAI API key (needed for lexical-graph and entity-graph)
OPENAI_API_KEY=${OPENAI_API_KEY}

# Model names
EMBEDDING_MODEL=${EMBEDDING_MODEL}
EXTRACTION_MODEL=${EXTRACTION_MODEL}
EOF

  success ".env created at $ENV_FILE"
fi

# ─────────────────────────────────────────────────────────────
# 3. Source .env
# ─────────────────────────────────────────────────────────────
# Export every non-comment, non-blank line
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

NEO4J_URI="${NEO4J_URI:-neo4j://localhost:7687}"
NEO4J_USERNAME="${NEO4J_USERNAME:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"
NEO4J_DATABASE="${NEO4J_DATABASE:-neo4j}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-text-embedding-3-small}"
EXTRACTION_MODEL="${EXTRACTION_MODEL:-gpt-5-mini}"

# ─────────────────────────────────────────────────────────────
# 4. Clone graphrag server
# ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}── Cloning neo4j-graphrag MCP server ─────────────${RESET}"

GRAPHRAG_DIR="$WORKSPACE_DIR/mcp-neo4j-graphrag"
if [ ! -d "$GRAPHRAG_DIR" ]; then
  if ! command -v git &> /dev/null; then
    error "git is not installed. Cannot clone mcp-neo4j-graphrag."
    exit 1
  fi
  info "Cloning mcp-neo4j-graphrag..."
  git clone --depth 1 https://github.com/neo4j-field/mcp-neo4j-graphrag "$GRAPHRAG_DIR" --quiet
  # Pin to Python 3.12 — grpcio has no pre-built wheels for Python 3.13+ on arm64 yet
  echo "3.12" > "$GRAPHRAG_DIR/.python-version"
  success "mcp-neo4j-graphrag cloned"
else
  info "mcp-neo4j-graphrag already present, skipping clone"
fi

# ─────────────────────────────────────────────────────────────
# 5. uv sync for each local server
# ─────────────────────────────────────────────────────────────

# Helper: sync a server directory, with optional extra flags (e.g. --extra docling)
sync_server() {
  local server_dir="$1"; shift
  local abs_dir="$WORKSPACE_DIR/$server_dir"
  if [ ! -d "$abs_dir" ]; then
    warn "$server_dir directory not found, skipping"
    return 0
  fi
  info "uv sync → $server_dir"
  if ! uv sync --directory "$abs_dir" "$@"; then
    error "Failed to install dependencies for $server_dir"
    error "Run manually: uv sync --directory $abs_dir"
    exit 1
  fi
  success "$server_dir dependencies ready"
}

# ─────────────────────────────────────────────────────────────
# 5a. Optional: docling for advanced PDF parsing
# ─────────────────────────────────────────────────────────────
INSTALL_DOCLING="${INSTALL_DOCLING:-}"

if [ -z "$INSTALL_DOCLING" ]; then
  echo ""
  echo -e "${BOLD}── Optional: advanced PDF parsing (docling) ──────${RESET}"
  echo "  Enables the 'docling' parse mode in neo4j-lexical-graph."
  echo "  Requires ~1-2 GB download (PyTorch + transformer models)."
  echo ""
  read -r -p "  Install docling? [y/N]: " input_docling
  case "$input_docling" in
    [Yy]|[Yy][Ee][Ss]) INSTALL_DOCLING=true ;;
    *) INSTALL_DOCLING=false ;;
  esac
  echo "" >> "$ENV_FILE"
  echo "# Optional dependencies" >> "$ENV_FILE"
  echo "INSTALL_DOCLING=${INSTALL_DOCLING}" >> "$ENV_FILE"
fi

echo ""
echo -e "${BOLD}── Installing local MCP server dependencies ──────${RESET}"

sync_server mcp-neo4j-ingest

info "Verifying neo4j-ingest imports..."
if ! uv --directory "$WORKSPACE_DIR/mcp-neo4j-ingest" run python -c "import mcp_neo4j_ingest" 2>&1; then
  error "neo4j-ingest failed import check — check NEO4J credentials in .env"
  exit 1
fi
success "neo4j-ingest import OK"

if [ "$INSTALL_DOCLING" = "true" ]; then
  sync_server mcp-neo4j-lexical-graph --extra docling
else
  sync_server mcp-neo4j-lexical-graph
fi
sync_server mcp-neo4j-entity-graph
sync_server mcp-neo4j-graphrag

# ─────────────────────────────────────────────────────────────
# 6. Optional: BigQuery via toolbox
# ─────────────────────────────────────────────────────────────
BIGQUERY_PROJECT="${BIGQUERY_PROJECT:-}"
INCLUDE_BIGQUERY=false

if command -v toolbox &> /dev/null; then
  echo ""
  echo -e "${BOLD}── BigQuery (optional) ───────────────────────────${RESET}"
  info "Google MCP Toolbox found: $(toolbox --version 2>/dev/null || echo 'installed')"

  if [ -z "$BIGQUERY_PROJECT" ]; then
    read -r -p "  BIGQUERY_PROJECT (leave blank to skip): " input_bq
    BIGQUERY_PROJECT="${input_bq:-}"
  fi

  if [ -n "$BIGQUERY_PROJECT" ]; then
    INCLUDE_BIGQUERY=true
    # Persist to .env if not already there
    if ! grep -q "^BIGQUERY_PROJECT=" "$ENV_FILE" 2>/dev/null; then
      echo "" >> "$ENV_FILE"
      echo "# BigQuery (optional)" >> "$ENV_FILE"
      echo "BIGQUERY_PROJECT=${BIGQUERY_PROJECT}" >> "$ENV_FILE"
    fi
    success "BigQuery will be configured for project: $BIGQUERY_PROJECT"
  else
    info "Skipping BigQuery configuration."
  fi
fi

# ─────────────────────────────────────────────────────────────
# 7. Generate mcp.json
# ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}── Generating MCP configuration ──────────────────${RESET}"

generate_mcp_json() {
  local output_file="$1"

  # Build the bigquery block conditionally
  local bigquery_block=""
  if [ "$INCLUDE_BIGQUERY" = true ]; then
    bigquery_block=",
    \"bigquery\": {
      \"command\": \"toolbox\",
      \"args\": [\"--prebuilt\", \"bigquery\", \"--stdio\"],
      \"env\": {
        \"BIGQUERY_PROJECT\": \"${BIGQUERY_PROJECT}\"
      }
    }"
  fi

  cat > "$output_file" << MCPEOF
{
  "mcpServers": {
    "neo4j-data-modeling": {
      "command": "uvx",
      "args": ["mcp-neo4j-data-modeling@0.8.2", "--transport", "stdio"]
    },
    "neo4j-ingest": {
      "command": "uv",
      "args": ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-ingest", "run", "mcp-neo4j-ingest"]
    },
    "neo4j-lexical-graph": {
      "command": "uv",
      "args": ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-lexical-graph", "run", "mcp-neo4j-lexical-graph"]
    },
    "neo4j-entity-graph": {
      "command": "uv",
      "args": ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-entity-graph", "run", "mcp-neo4j-entity-graph"]
    },
    "neo4j-graphrag": {
      "command": "uv",
      "args": ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-graphrag", "run", "mcp-neo4j-graphrag"]
    }${bigquery_block}
  }
}
MCPEOF
}

mkdir -p "$WORKSPACE_DIR/.cursor"

generate_mcp_json "$WORKSPACE_DIR/.cursor/mcp.json"
success ".cursor/mcp.json written"

generate_mcp_json "$WORKSPACE_DIR/.mcp.json"
success ".mcp.json written (Claude Code project scope)"

# ─────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  Setup complete!                               ${RESET}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════${RESET}"
echo ""
echo "  Next steps:"
echo "    • Open this folder in Cursor — MCP servers will load automatically"
echo "    • Or run: claude  (then /setup-workspace to verify)"
echo ""
echo "  Re-run this script any time to regenerate mcp.json files."
echo ""
