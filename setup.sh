#!/usr/bin/env bash
set -euo pipefail
umask 077

CHECK_MODEL=false
for setup_option in "$@"; do
  case "$setup_option" in
    --check-model) CHECK_MODEL=true ;;
    --help|-h) echo "Usage: ./setup.sh [--check-model]"; echo "--check-model: one small paid structured-output request before config generation"; exit 0 ;;
    *) echo "Unknown setup option: $setup_option" >&2; exit 2 ;;
  esac
done
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required to parse dotenv safely; install python3 and retry." >&2
  exit 1
fi

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
  echo "  Examples: text-embedding-3-small, gpt-6-luna"
  echo ""

  read -r -p "  EMBEDDING_MODEL  [text-embedding-3-small]: " input_embed
  EMBEDDING_MODEL="${input_embed:-text-embedding-3-small}"

  read -r -p "  EXTRACTION_MODEL [gpt-6-luna]: " input_extract
  EXTRACTION_MODEL="${input_extract:-gpt-6-luna}"

  # Serialize credentials as literal dotenv values, never shell source.
  export NEO4J_URI NEO4J_USERNAME NEO4J_PASSWORD NEO4J_DATABASE
  export OPENAI_API_KEY EMBEDDING_MODEL EXTRACTION_MODEL
  python3 "$WORKSPACE_DIR/scripts/setup-env.py" create "$ENV_FILE"

  success ".env created at $ENV_FILE"
fi

# ─────────────────────────────────────────────────────────────
# 3. Load .env as data (no shell evaluation or variable interpolation)
# ─────────────────────────────────────────────────────────────
chmod 600 "$ENV_FILE"
python3 "$WORKSPACE_DIR/scripts/setup-env.py" check "$ENV_FILE"
while IFS= read -r -d '' setup_key && IFS= read -r -d '' setup_value; do
  export "$setup_key=$setup_value"
done < <(python3 "$WORKSPACE_DIR/scripts/setup-env.py" export "$ENV_FILE")

NEO4J_URI="${NEO4J_URI:-neo4j://localhost:7687}"
NEO4J_USERNAME="${NEO4J_USERNAME:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"
NEO4J_DATABASE="${NEO4J_DATABASE:-neo4j}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-text-embedding-3-small}"
EXTRACTION_MODEL="${EXTRACTION_MODEL:-gpt-6-luna}"

# ─────────────────────────────────────────────────────────────
# 4. Clone graphrag server
# ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}── Cloning neo4j-graphrag MCP server ─────────────${RESET}"

GRAPHRAG_DIR="$WORKSPACE_DIR/mcp-neo4j-graphrag"
source "$WORKSPACE_DIR/scripts/setup-graphrag.sh"
ensure_graphrag_checkout "$GRAPHRAG_DIR" \
  "$WORKSPACE_DIR/mcp-neo4j-proxy/src/mcp_neo4j_proxy/graphrag_revision.txt"

# ─────────────────────────────────────────────────────────────
# 5. uv sync for each local server
# ─────────────────────────────────────────────────────────────

# Dependency setup is isolated from credentials/config generation for testing.
source "$WORKSPACE_DIR/scripts/setup-dependencies.sh"

echo ""
echo -e "${BOLD}── Installing local MCP server dependencies ──────${RESET}"
info "Docling is included in the standard lexical-graph environment."
info "Its PDF/ML dependencies can require substantial downloads; first use may fetch additional model assets."
info "Installation time depends on platform, connection and cache; per-server sync times follow."
sync_local_servers

if [ "$CHECK_MODEL" = true ]; then
  info "Checking extraction model structured output (one small provider request)..."
  uv --directory "$WORKSPACE_DIR/mcp-neo4j-entity-graph" run python \
    "$WORKSPACE_DIR/scripts/check-extraction-model.py"
else
  info "Model provider check not requested. Before ingestion, run ./setup.sh --check-model (one small request)."
fi

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

generate_gemini_settings_json() {
  local output_file="$1"

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

  cat > "$output_file" << GEMINIEOF
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
GEMINIEOF
}

generate_vscode_mcp_json() {
  local output_file="$1"

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

  cat > "$output_file" << VSCODEEOF
{
  "servers": {
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
VSCODEEOF
}

generate_opencode_json() {
  local output_file="$1"

  local bigquery_block=""
  if [ "$INCLUDE_BIGQUERY" = true ]; then
    bigquery_block=",
    \"bigquery\": {
      \"type\": \"local\",
      \"command\": [\"toolbox\", \"--prebuilt\", \"bigquery\", \"--stdio\"],
      \"enabled\": true,
      \"environment\": {
        \"BIGQUERY_PROJECT\": \"${BIGQUERY_PROJECT}\"
      }
    }"
  fi

  cat > "$output_file" << OPENCODEEOF
{
  "\$schema": "https://opencode.ai/config.json",
  "mcp": {
    "neo4j-data-modeling": {
      "type": "local",
      "command": ["uvx", "mcp-neo4j-data-modeling@0.8.2", "--transport", "stdio"],
      "enabled": true
    },
    "neo4j-ingest": {
      "type": "local",
      "command": ["uv", "--directory", "${WORKSPACE_DIR}/mcp-neo4j-ingest", "run", "mcp-neo4j-ingest"],
      "enabled": true
    },
    "neo4j-lexical-graph": {
      "type": "local",
      "command": ["uv", "--directory", "${WORKSPACE_DIR}/mcp-neo4j-lexical-graph", "run", "mcp-neo4j-lexical-graph"],
      "enabled": true
    },
    "neo4j-entity-graph": {
      "type": "local",
      "command": ["uv", "--directory", "${WORKSPACE_DIR}/mcp-neo4j-entity-graph", "run", "mcp-neo4j-entity-graph"],
      "enabled": true
    },
    "neo4j-graphrag": {
      "type": "local",
      "command": ["uv", "--directory", "${WORKSPACE_DIR}/mcp-neo4j-graphrag", "run", "mcp-neo4j-graphrag"],
      "enabled": true
    }${bigquery_block}
  }
}
OPENCODEEOF
}

generate_codex_toml() {
  local output_file="$1"

  cat > "$output_file" << CODEXEOF
[mcp_servers.neo4j-data-modeling]
command = "uvx"
args = ["mcp-neo4j-data-modeling@0.8.2", "--transport", "stdio"]
enabled = true

[mcp_servers.neo4j-ingest]
command = "uv"
args = ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-ingest", "run", "mcp-neo4j-ingest"]
enabled = true

[mcp_servers.neo4j-lexical-graph]
command = "uv"
args = ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-lexical-graph", "run", "mcp-neo4j-lexical-graph"]
enabled = true

[mcp_servers.neo4j-entity-graph]
command = "uv"
args = ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-entity-graph", "run", "mcp-neo4j-entity-graph"]
enabled = true

[mcp_servers.neo4j-graphrag]
command = "uv"
args = ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-graphrag", "run", "mcp-neo4j-graphrag"]
enabled = true
CODEXEOF

  if [ "$INCLUDE_BIGQUERY" = true ]; then
    cat >> "$output_file" << CODEXBQEOF

[mcp_servers.bigquery]
command = "toolbox"
args = ["--prebuilt", "bigquery", "--stdio"]
enabled = true

[mcp_servers.bigquery.env]
BIGQUERY_PROJECT = "${BIGQUERY_PROJECT}"
CODEXBQEOF
  fi
}

generate_vibe_config_toml() {
  local output_file="$1"

  cat > "$output_file" << VIBEEOF
[[mcp_servers]]
name = "neo4j-data-modeling"
transport = "stdio"
command = "uvx"
args = ["mcp-neo4j-data-modeling@0.8.2", "--transport", "stdio"]

[[mcp_servers]]
name = "neo4j-ingest"
transport = "stdio"
command = "uv"
args = ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-ingest", "run", "mcp-neo4j-ingest"]

[[mcp_servers]]
name = "neo4j-lexical-graph"
transport = "stdio"
command = "uv"
args = ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-lexical-graph", "run", "mcp-neo4j-lexical-graph"]

[[mcp_servers]]
name = "neo4j-entity-graph"
transport = "stdio"
command = "uv"
args = ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-entity-graph", "run", "mcp-neo4j-entity-graph"]

[[mcp_servers]]
name = "neo4j-graphrag"
transport = "stdio"
command = "uv"
args = ["--directory", "${WORKSPACE_DIR}/mcp-neo4j-graphrag", "run", "mcp-neo4j-graphrag"]
VIBEEOF

  if [ "$INCLUDE_BIGQUERY" = true ]; then
    cat >> "$output_file" << VIBEBQEOF

[[mcp_servers]]
name = "bigquery"
transport = "stdio"
command = "toolbox"
args = ["--prebuilt", "bigquery", "--stdio"]
env = { BIGQUERY_PROJECT = "${BIGQUERY_PROJECT}" }
VIBEBQEOF
  fi
}

mkdir -p "$WORKSPACE_DIR/.cursor"

generate_mcp_json "$WORKSPACE_DIR/.cursor/mcp.json"
success ".cursor/mcp.json written"

generate_mcp_json "$WORKSPACE_DIR/.mcp.json"
success ".mcp.json written (Claude Code project scope)"

mkdir -p "$WORKSPACE_DIR/.gemini"
generate_gemini_settings_json "$WORKSPACE_DIR/.gemini/settings.json"
success ".gemini/settings.json written (Gemini CLI)"

mkdir -p "$WORKSPACE_DIR/.vscode"
generate_vscode_mcp_json "$WORKSPACE_DIR/.vscode/mcp.json"
success ".vscode/mcp.json written (GitHub Copilot VS Code)"

generate_opencode_json "$WORKSPACE_DIR/opencode.json"
success "opencode.json written (OpenCode)"

mkdir -p "$WORKSPACE_DIR/.codex"
generate_codex_toml "$WORKSPACE_DIR/.codex/config.toml"
success ".codex/config.toml written (OpenAI Codex CLI)"

mkdir -p "$WORKSPACE_DIR/.vibe"
generate_vibe_config_toml "$WORKSPACE_DIR/.vibe/config.toml"
success ".vibe/config.toml written (Mistral Vibe)"

# ─────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  Setup complete!                               ${RESET}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════${RESET}"
echo ""
echo "  MCP configs generated for 7 tools:"
echo "    • Claude Code    → .mcp.json"
echo "    • Cursor         → .cursor/mcp.json"
echo "    • Gemini CLI     → .gemini/settings.json"
echo "    • Copilot VS Code→ .vscode/mcp.json"
echo "    • OpenCode       → opencode.json"
echo "    • Codex CLI      → .codex/config.toml"
echo "    • Mistral Vibe   → .vibe/config.toml"
echo ""
echo "  Open the workspace in your AI coding tool:"
echo "    • Claude Code    : claude  (then /setup-workspace to verify)"
echo "    • Cursor         : open this folder in Cursor"
echo "    • Gemini CLI     : gemini"
echo "    • Copilot VS Code: open this folder in VS Code, use Agent mode"
echo "    • OpenCode       : opencode"
echo "    • Codex CLI      : codex"
echo "    • Mistral Vibe   : vibe  (trust the folder when prompted)"
echo ""
echo "  Re-run this script any time to regenerate config files."
echo ""
