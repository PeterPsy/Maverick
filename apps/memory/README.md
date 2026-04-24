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
./scripts/maverick app validate memory --workspace default
./scripts/maverick app register-local memory --workspace default
./scripts/maverick app install-local memory --workspace default
./scripts/maverick app status memory --workspace default
./scripts/maverick app package memory --workspace default
```
