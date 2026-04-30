# Memory

Workspace knowledge graph for durable agent and user memory.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The frontend is a React/Vite graph workspace with search, remember, live refresh, canvas graph navigation, readable node inspection, references, relationship browsing, and agent context preview.
- The contract declares the bundled `memory-ops` skill, persisted view-state actions, and the `node` reference entity.
- App-owned storage lives under `data/memory/` for the SQLite graph and attached artifacts.
- Memory is one of the repository reference apps for complete stateful contract coverage.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id memory --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id memory --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id memory --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id memory --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id memory --workspace default --json
```
