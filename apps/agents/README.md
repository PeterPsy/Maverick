# Agents

Workspace app for managing agent roles, prompt composition, and runtime-ready agent types.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- Bundled skill templates live under `skills/`; the contract declares `agents-ops`.
- The app currently exposes reference entities for `agent_type` and `role_prompt`.
- The app now declares persisted `view_surfaces` for query filters and curated agent or role selections.

## SDK Flow

```bash
./scripts/maverick app validate agents --workspace default
./scripts/maverick app register-local agents --workspace default
./scripts/maverick app install-local agents --workspace default
./scripts/maverick app status agents --workspace default
./scripts/maverick app package agents --workspace default
```
