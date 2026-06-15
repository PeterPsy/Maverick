# Agents

Workspace app for managing agent roles, prompt composition, and agent type definitions.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- Agents declares a required `runtime-skills` dependency on the `skill.catalog` interface. The UI resolves the selected provider through the generic dependency payload instead of hardcoding the Skills app id.
- Bundled skill templates live under `skills/`; the contract declares `agents-ops`.
- The app currently exposes reference entities for `agent_type` and `role_prompt`.
- The app now declares persisted `view_surfaces` for query filters and curated agent or role selections.
- Agents declares `base-shell` sidebar widgets for `shell.sidebar.primary` and `shell.sidebar.footer`. The app-owned primary widget renders agent search/list state, while the footer widget owns the New Agent action.
- The main Agents iframe no longer renders an internal sidebar. It listens for `maverick.app.navigate` with `agent_type_id` or `app_page: "agent-types/<id>"` to select an agent, and `new_agent` plus `new_agent_request_id` to open the create modal. When selection changes, it emits `maverick.app.selection-changed` so shell-hosted Agents widgets can keep their active row synchronized with the detail iframe.
- Agents does not own runtime execution or orchestration. It owns only agent definitions, role prompts, and prompt preview; a future Fleet/Orchestrations app may consume those definitions when that app exists and is installed.
- Runtime execution belongs to Chat or another installed runtime-owning app through the generic core runtime surfaces. Agents does not launch runtime sessions or persist runtime instances.
- Empty `skill_ids` on an agent type mean "all enabled workspace skills" when a runtime session is launched; explicit `skill_ids` narrow the runtime skill set.

## CLI And MCP Operations

- `maverick app agents cli run agents --json` and `maverick app agents mcp call maverick_agents_app --json` return a compact `operations.manifest` by default.
- Use `catalog.compact` or `agents_catalog_compact` for token-efficient catalog reads; full `catalog` is opt-in because it includes common prompt and role instructions.
- Use `get_agent_definition` or `agents_get_agent_definition` when full prompt content is needed for one explicit agent type id.
- Use `upsert_agent_definition` or `agents_upsert_agent_definition` to create or update a role prompt plus its agent type in one idempotent write path.
- CLI and MCP discovery schemas live in `cli/command_schemas.json` and `mcp/tool_schemas.json` so `list` and `inspect` stay useful without reading app source.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id agents --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id agents --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id agents --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id agents --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id agents --workspace default --json
```
