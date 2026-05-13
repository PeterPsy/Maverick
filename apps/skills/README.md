# Skills

Workspace app for creating, editing, validating, and deleting workspace-owned runtime skills.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The frontend follows the same shell-owned/sidebar-widget split as Agents: the full app route renders the skill detail editor, while `skills-sidebar` and `skills-sidebar-footer` provide the base-shell sidebar body and create action.
- The contract now declares the bundled skill template ids copied by the Skills app into workspace-owned skill data: `generate-image`, `maverick-app-creator`, `maverick-code-skill`, and `skills-ops`.
- `skill` is the current reference entity and app-owned state lives under `data/skills/`.
- Persisted `view_surfaces` cover catalog filters and curated skill selections.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id skills --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id skills --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id skills --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id skills --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id skills --workspace default --json
```
