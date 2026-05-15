# Memory Architecture

Date: 2026-05-15

## Purpose

Define the target architecture for the built-in Memory app.

Memory is a visual knowledge map backed by an internal compiled wiki. The app must not become a second `llmwiki` app and the core must not own memory semantics.

## Product Shape

Memory's user-facing surface is a graph of durable workspace knowledge:

- nodes represent human-meaningful entities such as notes, facts, files, app-entity references, people, companies, projects, topics, decisions, and questions
- edges represent typed relationships such as support, contradiction, derivation, dependency, ownership, and topic membership
- the node inspector is the place where users see evidence, relationships, compiled summaries, claims, citations, freshness, and lint findings

The compiled wiki layer is internal app-owned data. It is inspectable evidence, not a separate wiki navigation product.

## Storage Boundary

All Memory data lives under:

```text
workspaces/<workspace_id>/data/memory/
```

The app may use SQLite and app-owned artifacts inside that root. The core hosts Memory through app contracts, CLI, MCP, backend, frontend, hooks, and data events, but it must not read or enforce Memory's SQLite schema.

## Compiled Wiki Model

The internal wiki model is app-owned and should include:

- `sources`: stable references to Storage files, generated artifacts, chat/app entities, URLs, or other workspace-owned material
- `source_versions`: observed hashes and extracted text or extracted-reference pointers
- `node_source_links`: explicit node-to-source relationships
- `wiki_pages`: compiled markdown for a node or topic
- `claims`: atomic statements derived from node content and sources
- `citations`: claim-to-source evidence links
- `compile_runs`: compilation provenance and input hashes
- `lint_findings`: current quality findings such as missing citation, contradiction, stale page, orphan node, or empty content

Raw sources stay authoritative. Compiled pages and claims are derived artifacts that can be regenerated.

Deterministic compilation must not create placeholder citations just because a source is linked to a node. Source links show provenance candidates; citations require credible evidence such as a chunk, locator, range, quote, or extracted-reference pointer that supports the specific claim. Until that exists, claims remain uncited and lint should report `missing_citation`.

When source extraction is unavailable, Memory may store a source version with `metadata.hash_kind = reference_snapshot` to capture the observed reference fields. That snapshot is not a content hash. For workspace files, Memory should use observed file-byte hashes when the file can be resolved from the workspace root.

## Runtime Surfaces

Memory exposes agent-facing surfaces through the app contract:

- `memory_context` returns context packs and includes compiled page data when available
- `memory_inspect_node` returns node details plus compiled page, claims, citations, sources, and lint findings
- `memory_search` searches graph nodes plus compiled page and claim text
- `memory_compile` compiles one node into the internal wiki layer
- `memory_lint` refreshes quality findings
- `memory_wiki_query` searches compiled wiki pages and claims directly

The first compiler may be deterministic and use existing node text, references, and relationships. LLM-assisted compilation can be added later, but it must preserve citations, input provenance, lint results, and source version identity.

## UI Rule

Do not add a separate Wiki tab or app. The graph stays primary. Compiled wiki content appears in the node inspector and in agent-facing context payloads.
