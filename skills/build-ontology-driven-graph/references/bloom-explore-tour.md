# Bloom / Explore visual tour

How to walk a non-technical user through Neo4j's graph visualization UI. Used in Phase 4 (after writing the structural ontology) and Phase 7 (after extraction).

**Naming note**: in newer Neo4j Desktop versions Bloom has been renamed to **Explore**. The interface is the same. This tour says "Bloom or Explore" interchangeably — let the user use whichever name they see.

**Critical**: Bloom is **not** a Cypher console. The search bar uses a graph-pattern search vocabulary (clicking nodes/relationships from a dropdown), **not** Cypher syntax. Telling the user to type `MATCH (n) RETURN n` will fail silently — they'll think nothing works.

Reference: https://neo4j.com/docs/bloom-user-guide/current/bloom-tutorial/graph-pattern-search/

## How Bloom's search bar works

When the user clicks the search bar, a dropdown appears with available node labels, relationship types, and configured search phrases. To build a pattern:

1. **Click a node** from the dropdown — that's the first node in the pattern. To match any label, click `(any)`.
2. **Click a relationship** — to match any type, click `(any)`. The arrow defaults to undirected (`-<(any)>-`); the user can flip direction if they care.
3. **Click another node** — to match any label, `(any)` again.
4. **Press Enter (or the play icon)** — Bloom runs the pattern and renders matching paths.

The visible result is the pattern `(any)-<(any)>-(any)` — every relationship in the graph. That's the whole-graph view.

## How interactions work in the scene

| Gesture | Effect |
|---|---|
| **Hover** over a node | Shows label and a few preview properties as a tooltip |
| **Single click** | Selects or deselects the node (highlight) — does NOT open properties |
| **Double click** | Opens the **Inspector** panel with the node's full property list |
| **Right click** | Context menu — expand neighbors, find shortest path, dismiss, etc. |

Note the single vs double click distinction — first-time users almost always single-click expecting to see properties and assume nothing happens. Tell them up front.

## Phase 4 tour — looking at the ontology meta-model

This is the harder of the two tours because the user is looking at the *meta-model* — the model of their ontology, not the data itself. Slow down here.

### Step 1 — Switch to the Ontology database

> "First make sure you're looking at the **Ontology** database (not the Documents one). The database picker is at the top of the screen — pick whichever database you set up for the ontology."

If they don't see a picker, they may already be on it. Confirm by running `ontology_get_neo4j_schema_and_indexes` and comparing the labels they describe with what's actually there.

### Step 2 — Show the whole graph

Bloom doesn't have a "show all" button. The pattern `(any)-<(any)>-(any)` is the equivalent.

> "Click in the search bar at the top. A dropdown will appear listing your node labels and relationship types. We're going to build a pattern that matches every relationship — that effectively shows you the whole ontology.
>
> 1. Click `(any)` for the first node.
> 2. Click `(any)` for the relationship.
> 3. Click `(any)` for the second node.
>
> The search bar should now show: `(any) - (any) - (any)`. Press Enter or the play icon. The full ontology graph appears."

If the user reports nothing rendered, run `MATCH (n)-[r]-(m) RETURN count(r) AS rels` via `ontology_read_neo4j_cypher` to verify there *are* relationships — if zero, their writes didn't land.

### Step 3 — Explain the meta-model

This is where most users get confused. Don't skip it.

> "What you're seeing is your ontology rendered **as a graph**. But this is a *meta-model* — a model that describes your ontology, not your actual document data. Each colored node is a different *kind* of meta-element:
>
> - **`:Ontology`** (one node, the hub) — the container for everything that follows.
> - **`:NodeType`** nodes — these will become the actual entity types when we extract from documents. So `:NodeType {name: 'Tool'}` here will become `:Tool` nodes in your Documents database after extraction.
> - **`:PropertyDef`** nodes — properties on each entity type. `:PropertyDef {name: 'bestFor'}` linked to a `:NodeType {name: 'Tool'}` means every extracted Tool will have a `bestFor` property.
> - **`:RelationshipType`** nodes — and here's the part that looks weird: the *relationships you'll see in your knowledge graph* are themselves **nodes** here. We do that on purpose — it lets you store metadata about the relationship (its name, description, source/target types) and visualize it like everything else.
> - **`:AliasMap` / `:Alias`** — alias mappings that normalize values during extraction (e.g. 'NY' → 'New York').
> - **`:Blocklist` / `:BlockedTerm`** — values to skip during extraction.
>
> The **lines between nodes** are meta-relationships, not your data relationships:
> - `:CONTAINS` — Ontology to its NodeType / RelationshipType members
> - `:HAS_PROPERTY` — NodeType (or RelationshipType) to its properties
> - `:FROM` and `:TO` — these are special: they connect a `:RelationshipType` to its source `:NodeType` and target `:NodeType`. Together they say 'this kind of relationship goes from X to Y'.
> - `:DEFINES` — Ontology to its alias maps and blocklists
> - `:USES_ALIAS_MAP` / `:USES_BLOCKLIST` — PropertyDef to the map/list it uses"

### Step 4 — Demonstrate the conceptual leap

After the explanation, ground it in their domain. Pick one of their NodeTypes and walk through:

> "Take **`:NodeType {name: '<their entity>'}`** here. After extraction, your Documents database will have many `:<theirEntity>` nodes — one for each <their entity> we found in the documents. Each will have the properties listed by the connected `:PropertyDef` nodes. The `:RelationshipType` nodes here will become arrows between extracted nodes there."

This is the moment the meta-model clicks. Worth spending a sentence on.

### Step 5 — Click around

> "Single-click any node to select it (you'll see a highlight). Double-click to open the **Inspector** panel — that's where you see the full properties. Try double-clicking a `:NodeType` to see its name and description; try a `:PropertyDef` to see its type, whether it's a key, and which normalizer is applied (if any). Right-click a node for more options like expanding to see what it's connected to."

### Step 6 — Editing in place

> "If you spot something to change — a description that's wrong, a property you want to remove — you can edit directly in the Inspector. After your edits, come back to me and tell me, and I'll re-read the ontology and re-validate."

### Step 7 — Wrap up

> "When you've had a look, tell me one of:
> - **looks good, continue** — I'll move on to setting up extraction rules.
> - **I edited something** — I'll re-read the ontology.
> - **I have questions about what I'm seeing** — happy to explain."

## Phase 7 tour — looking at the extracted graph

After extraction, switch to the Documents database. Now what the user sees IS their actual data, not a meta-model — easier to grasp.

### Step 1 — Switch databases

> "Switch the database picker to the **Documents** database — the one where the PDFs were ingested. The Ontology database doesn't have your extracted data."

### Step 2 — See the lexical layer first

> "Click in the search bar. Click `Document` (or whatever it's called in your perspective), then `(any)` relationship, then `Chunk`. Press Enter. You'll see your documents with their text chunks. This is the raw text layer."

If the perspective doesn't expose `Document` or `Chunk` as labels in the dropdown, the user may need to refresh the perspective from the database. Tell them: "If `Document` doesn't appear in the dropdown, click the perspective panel and refresh categories."

### Step 3 — See the extracted entities

> "Now do `(any) - (any) - (any)` to see the whole graph. The colored nodes that aren't `:Document` or `:Chunk` are the entities we extracted — Tools, Metrics, BestPractices, whatever your ontology defined."

### Step 4 — Trace the network

> "Pick any extracted entity, single-click to select, then right-click → **Reveal connected nodes** (or **Expand**, depending on your version). This walks the graph one hop at a time and shows you what that entity is connected to. This is the moment graph value lands — you can see, for example, that this `Tool` is used by these `Practitioners`, applies to these `UseCases`, has these `Risks`, all in one view."

### Step 5 — Double-click for details

> "Double-click any extracted entity to see its full properties — the same fields we set up in the ontology, now with real values pulled from the documents and normalized."

## Common confusions

| What the user says | What's happening | What to tell them |
|---|---|---|
| "I see nothing" / "the search did nothing" | They typed Cypher, or pressed Enter on an empty search bar | Walk them through the click-click-click pattern build |
| "I see only the database name list" | They never clicked into the search bar | Tell them to click the search bar to open the dropdown |
| "I clicked a node but no properties show up" | They single-clicked instead of double-clicking | Tell them to double-click for the Inspector |
| "I see Property nodes connected to my Contract — I thought properties weren't nodes" | They're on the **Ontology** DB; in the meta-model PropertyDef IS a node | Confirm the DB; switch to Documents DB to see real data |
| "Why are there 'arrows' that look like nodes between things?" | RelationshipType nodes — meta-model again | Re-explain the meta-model briefly |
| "The label dropdown doesn't show my entity types" | Perspective is stale | Tell them to refresh the perspective from the database |

## What you should NOT teach them

The user doesn't need to learn Cypher, perspective configuration in depth, or styling. The goal is for them to **recognize and explore** what you've built — not to become a graph engineer. Keep instructions one gesture at a time.

## When to refer the user to docs

If the user wants more depth on Bloom/Explore than this tour covers, point them at:
- Search bar reference: https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour/search-bar/
- Pattern search tutorial: https://neo4j.com/docs/bloom-user-guide/current/bloom-tutorial/graph-pattern-search/
- Scene interactions: https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour/bloom-scene-interactions/

(For Aura users, the Explore docs are equivalent under https://neo4j.com/docs/aura/explore/.)
