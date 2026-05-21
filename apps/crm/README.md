# CRM

Workspace-local Maverick CRM app for account, contact, deal, activity, task, note, import/export, and agent-facing CRM workflows.

The implementation is native Maverick source. External CRM projects informed the domain and UX direction, but this app does not copy Relaticle, Twenty, EspoCRM, or Krayin code. CRM behavior stays app-owned; the core only validates, registers, mounts, and invokes the declared contract surfaces.

## Repository Model

This is a workspace-local app source tree versioned under the separate `loopinos-apps` repository at `apps/crm/`. It is intentionally independent from the Maverick/Loopinos core repository.

Track app source, tests, contract files, and intentional frontend build artifacts here. Do not track workspace data such as `data/crm/crm.sqlite`, generated caches, `node_modules/`, or Python bytecode.

## Surfaces

- Frontend: `frontend/dist`, rebuilt from React/Vite sources under `frontend/src`.
- Backend: `backend/app_backend.py`, invoked through `/api/apps/crm/backend`.
- CLI: `crm`, described by `cli/command_schemas.json`.
- MCP: `crm_search`, `crm_get_record`, create/update tools for accounts, contacts, deals, tasks, and notes, deal movement, activity logging, import preview/commit, account summary, references, view state, and health.
- Widgets: `crm-sidebar` for the `base-shell` primary sidebar slot and `crm-sidebar-footer` for the compact footer action slot.
- Lifecycle hooks: install, migrate, export, import, and health check.
- Skill template: `skills/crm-ops/SKILL.md`.

## Storage

CRM data lives only under the workspace app data root:

```text
data/crm/
  .maverick-app.json
  crm.sqlite
  view_state.json
```

The SQLite schema is initialized idempotently by install and migrate hooks. The first release includes accounts, contacts, deals, pipelines, pipeline stages, activities, tasks, notes, events, and an embedded FTS index. Task and note records are first-class service, MCP, CLI/import, reference, and frontend entities. Tag, archive, and delete columns/tables are reserved schema surfaces and are not exposed as public CRM actions yet. The app does not store raw secrets; future external connectors must use core secret grants.

## MVP Scope

Included:

- Account, contact, deal, activity, task, and note persistence.
- Essential sales pipeline stages.
- Search, record lookup, account summary, and next-action listing.
- Small JSON/CSV import preview and commit for accounts, contacts, deals, activities, tasks, and notes.
- JSON export through the app service and export hook, with lifecycle import round-trip support for complete CRM export payloads through service, CLI, and MCP schemas.
- Dense operational UI with list/detail/pipeline views, shell/widget navigation handling, task/note views, persisted search filter rendering, custom view rendering with referenced-record hydration, footer widget create-menu intent handling, create chooser and create/edit composer forms, and import preview before commit.
- Base-shell sidebar and sidebar footer widgets.

Deferred intentionally:

- Live external CRM sync.
- Advanced custom fields and saved views.
- Public tag, archive, and delete workflows.
- Persistent import job queues.
- Deep permission model beyond platform workspace enablement.
- AI scoring that cannot be deterministically verified.

## SDK Lifecycle

```bash
maverick core cli run core.app-sdk.validate --app-id crm --json
maverick core cli run core.app-sdk.register-local --app-id crm --json
maverick core cli run core.app-sdk.install-local --app-id crm --json
maverick core cli run core.app-sdk.status --app-id crm --json
maverick app crm frontend build --json
```

After installation, discover executable surfaces with:

```bash
maverick app crm cli list --json
maverick app crm mcp list --json
```
