# Memory

Workspace knowledge graph for durable agent and user memory.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The frontend is a React/Vite graph workspace with a dark token-aligned canvas, live refresh, canvas graph navigation, readable node inspection, references, relationship browsing, and a create-node modal.
- The base-shell sidebar widgets provide Memory search, node navigation, a footer context-preview action that opens the app modal, and an icon-only create action that opens the app create modal.
- The contract declares the bundled `memory-ops` skill, persisted view-state actions, and the `node` reference entity.
- App-owned storage lives under `data/memory/` for the SQLite graph and attached artifacts.
- Memory is one of the repository reference apps for complete stateful contract coverage.

## Runtime Behavior

- Frontend backend calls derive the mounted app id from `/apps/<mount_app_id>/...`, so workspace-local forks use their local backend mount instead of a hardcoded `memory` route.
- Frontend backend calls normalize HTTP and app-level errors and support abort/timeout handling for stale requests.
- The graph action returns a lightweight node/edge summary for canvas and sidebar rendering. Full external references and edge details are loaded through `inspect`.
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
