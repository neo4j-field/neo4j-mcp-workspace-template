# Claude Desktop Skills

Skills in this directory target **Claude Desktop only** (used together with the [Neo4j MCP Workspace DXT](../docs/CLAUDE_DESKTOP.md)). They are intentionally **not** symlinked into `.claude/skills/`, so Claude Code does not auto-load them — Claude Code users have `/develop-neo4j-graph` instead.

## Available skills

| Skill | Audience | What it does |
|-------|----------|-------------|
| [`build-ontology-driven-graph`](build-ontology-driven-graph/) | Domain experts, lawyers, analysts | Walks the user through ontology design in Neo4j, PDF ingestion, entity extraction, and Bloom-based refinement |

## Install in Claude Desktop

Each skill is distributed as a `.skill` zip on the [GitHub Releases](https://github.com/neo4j-field/neo4j-mcp-workspace-template/releases) page. To install:

1. Download the `.skill` file from the release
2. Drag-drop it into a Claude Desktop conversation
3. Claude Desktop installs it into its skills plugin directory

The skill is then available in any future Claude Desktop conversation — Claude will trigger it automatically when the user describes a matching task.

## Iterating on a skill (maintainers)

The source lives under `<skill-name>/`. To repackage after edits:

```bash
# Requires the skill-creator skill installed at ~/.claude/skills/skill-creator/
cd ~/.claude/skills/skill-creator
python3 -m scripts.package_skill \
  /path/to/neo4j-mcp-workspace-template/skills/build-ontology-driven-graph \
  /path/to/output-dir
```

This produces `<skill-name>.skill` (a zip with `.skill` extension). Attach it to a new GitHub Release tagged `skill-<name>-vX.Y.Z`.
