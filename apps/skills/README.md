# Skills

Workspace app for managing installed runtime skills and discovering reviewed public Agent Skills.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The frontend follows the same shell-owned/sidebar-widget split as Agents: the full app route separates installed skill management from prompts.chat discovery, while `skills-sidebar` and `skills-sidebar-footer` provide the local catalog and create action.
- `skills-ops` is the single bundled management skill. It covers local CRUD plus bounded public Agent Skill discovery without adding a second meta-skill.
- The `maverick_skills_app` MCP/CLI action surface exposes only public Agent Skill lookup from prompts.chat. Installation requires explicit confirmation bound to the reviewed content digest, preserves validated multi-file skills, records source attribution, and never replaces an existing workspace skill.
- The app never imports or caches the full prompts.chat dataset and never uses remote mutation endpoints.
- Generic prompts remain temporary content and are not stored in the runtime skill catalog.
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
