# Memory

Workspace visual knowledge map for durable agent and user memory.

Memory keeps the human product surface graph-first. Under the hood it compiles workspace sources into an agent-optimized internal LLM Wiki made of compiled pages, atomic claims, citations, source links, compile runs, and lint findings. The compiled wiki is not a separate user-facing app or route; it is evidence visible from node inspection and from agent-facing context surfaces.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The frontend is a React/Vite graph workspace with a dark token-aligned canvas, live refresh, canvas graph navigation, readable node inspection, compiled wiki evidence, references, relationship browsing, and a create-node modal.
- The base-shell sidebar widgets provide Memory search, node navigation, a footer context-preview action that opens the app modal, and an icon-only create action that opens the app create modal.
- The contract declares the bundled `memory-ops` skill, persisted view-state actions, `memory_compile`, `memory_lint`, `memory_wiki_query`, and the `node` reference entity.
- App-owned storage lives under `data/memory/` for the SQLite graph, internal wiki tables, and attached artifacts.
- Memory is one of the repository reference apps for complete stateful contract coverage.

## Runtime Behavior

- Frontend backend calls derive the mounted app id from `/apps/<mount_app_id>/...`, so workspace-local forks use their local backend mount instead of a hardcoded `memory` route.
- Frontend backend calls normalize HTTP and app-level errors and support abort/timeout handling for stale requests.
- The graph canvas uses pointer gestures across desktop and mobile: drag empty space to pan, drag a node to move/select it, pinch to zoom, and wheel to zoom on pointer devices.
- The graph action returns a lightweight node/edge summary for canvas and sidebar rendering. Full external references and edge details are loaded through `inspect`.
- `compile` deterministically builds the internal wiki page for a node from the current node text, external references, and relationships. It records source/version rows, claims, citations, a compile run, and current lint findings without calling an LLM yet.
- `inspect` returns the compiled page, claims, citations, source links, and lint findings for the selected node. `context` includes the compact compiled pack when one exists.
- `search` covers nodes plus compiled wiki page and claim text; `wiki_query` returns wiki-page and claim matches directly for agents.
- `lint` refreshes app-owned findings such as missing citations, contradictions, orphan nodes, empty content, and stale compiled pages.
- SQLite connections enable foreign keys, WAL, `busy_timeout`, and explicit write transactions. Schema creation is skipped after the current schema version has been installed.
- Numeric request fields reject non-finite values, and SQLite constraint failures are returned as validation errors instead of crashing entrypoints.
- Context retrieval is read-only by default. Audit telemetry for context generation is opt-in through `record_access_event`.
- Sidebar search text is widget-local. Persisted view-state changes are reserved for explicit view actions such as `set_custom_view`, `set_view_filter`, and `clear_custom_view`.

## SDK Flow

Validate the installation-level Memory source directly:

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id memory --app-root apps/memory --workspace default --json
```

Workspace-local registration and installation commands target a workspace-owned copy under `workspaces/default/apps/memory`:

```bash
./scripts/maverick core cli run core.app-sdk.register-local --app-id memory --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id memory --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id memory --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id memory --workspace default --json
```
