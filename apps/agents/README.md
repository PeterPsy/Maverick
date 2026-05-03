# Agents

Workspace app for managing agent roles, prompt composition, and agent type definitions.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- Bundled skill templates live under `skills/`; the contract declares `agents-ops`.
- The app currently exposes reference entities for `agent_type` and `role_prompt`.
- The app now declares persisted `view_surfaces` for query filters and curated agent or role selections.
- Agents declares `base-shell` sidebar widgets for `shell.sidebar.primary` and `shell.sidebar.footer`. The app-owned primary widget renders agent search/list state, while the footer widget owns the New Agent action.
- The main Agents iframe no longer renders an internal sidebar. It listens for `maverick.app.navigate` with `agent_type_id` or `app_page: "agent-types/<id>"` to select an agent, and `new_agent` plus `new_agent_request_id` to open the create modal. When selection changes, it emits `maverick.app.selection-changed` so shell-hosted Agents widgets can keep their active row synchronized with the detail iframe.
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
