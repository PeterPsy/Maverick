# Agents

Workspace app for managing agent roles, prompt composition, and agent type definitions.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- Bundled skill templates live under `skills/`; the contract declares `agents-ops`.
- The app currently exposes reference entities for `agent_type` and `role_prompt`.
- The app now declares persisted `view_surfaces` for query filters and curated agent or role selections.
- Fleet orchestration now lives in the workspace-local `fleet` app. Agents owns only agent definitions, role prompts, and prompt preview.
- Runtime execution belongs to Fleet, Chat, or another runtime-owning app through the generic core runtime surfaces. Agents does not launch runtime sessions or persist runtime instances.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id agents --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id agents --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id agents --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id agents --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id agents --workspace default --json
```
