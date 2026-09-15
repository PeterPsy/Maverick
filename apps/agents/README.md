# Agents

Workspace app for intentional custom agent definitions.

## Contract Notes

Each agent is one self-contained record: identity, instructions, enabled state,
and an explicit skill allowlist. There are no role records, common prompt,
implicit skills, trace settings, or prompt-composition preview. The app ships no
agents; Free Agent and Research remain fixed Chat runners.

Agents provides `agent.catalog`. `get_agent_definition` returns the exact
instructions consumed by Chat and orchestration, so a second prompt
materialization interface is unnecessary. Runtime execution remains owned by
Chat and core.

Bundled `agents-ops` is an optional explicit skill for managing the catalog.
The shell sidebar and main view use the same backend actions.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id agents --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id agents --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id agents --workspace default --json
```
