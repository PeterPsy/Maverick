# CRM

Workspace-local Maverick CRM app for lead, account, contact, deal, activity, task, note, typed custom fields, import/export, and agent-facing CRM workflows.

The implementation is native Maverick source. External CRM projects informed the domain and UX direction, but this app does not copy Relaticle, Twenty, EspoCRM, or Krayin code. CRM behavior stays app-owned; the core only validates, registers, mounts, and invokes the declared contract surfaces.

## Repository Model

This is a workspace-local app source tree versioned under the separate `loopinos-apps` repository at `apps/crm/`. It is intentionally independent from the Maverick/Loopinos core repository.

Track app source, tests, contract files, and intentional frontend build artifacts here. Do not track workspace data such as `data/crm/crm.sqlite`, generated caches, `node_modules/`, or Python bytecode.

## Surfaces

- Frontend: `frontend/dist`, rebuilt from React/Vite sources under `frontend/src`.
- Backend: `backend/app_backend.py`, invoked through `/api/apps/crm/backend`; the service router delegates larger domains to `backend/domains/`.
- CLI: `crm`, described by `cli/command_schemas.json`.
- MCP: a stable agent-facing subset for search/read, lead/account/contact/deal CRUD, task/note/activity creation and updates, deal movement, record archive/delete/tag/bulk/merge, timeline/audit/report/filter/dedupe, external references, typed custom field value reads/writes, deterministic enrichment, next actions, workflow proposal approve/apply/dismiss/reject lifecycle, account brief, import/export, reference resolution, and health. UI view state, saved views, custom-field definition management, and automation-rule administration stay backend/CLI helpers rather than public MCP tools.
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

The SQLite schema is initialized idempotently by install and migrate hooks. The current release includes leads, accounts, contacts, deals, configurable pipelines, pipeline stages, activities, tasks, notes, events, tags, record tags, saved views, typed custom field definitions/values, automation rules, workflow proposals, external reference snapshots, and an embedded FTS index. Task and note records are first-class service, MCP, CLI/import, reference, and frontend entities. Archive, soft-delete, tag, untag, bulk operations, lead conversion, saved views, timeline, audit log, native sales reports, duplicate discovery and merge, typed custom fields, deterministic enrichment, approvable workflow proposals, automation proposal generation, external reference linking, and import row validation are exposed through backend, CLI/MCP where appropriate, and the operational UI. The app does not store raw secrets; future external connectors must use core secret grants.

## MVP Scope

Included:

- Lead, account, contact, deal, activity, task, and note persistence.
- Lead conversion into account, contact, and optional deal records.
- Configurable sales pipeline stages with drag/drop deal movement in the UI.
- Search, record lookup, account summary, and next-action listing for open tasks only.
- Timeline retrieval for account, contact, deal, and lead records.
- External reference snapshots for linking CRM records to future Mail/Calendar records through declared CRM surfaces only. CRM stores `source_app_id`, source entity identity, link type, title, summary, occurrence time, and metadata; it does not read Mail or Calendar private data.
- Typed custom fields with schema/config discovery, validation, record values, filtering support, export/import round trip, and frontend detail rendering.
- Saved views, advanced local filters, bulk tag/archive actions, and duplicate detection for account/contact/lead email/domain data.
- Native sales reports for pipeline value by stage, weighted forecast, deal aging, lead conversion, overdue tasks, and activities by owner.
- Merge dedupe for leads, accounts, and contacts. Merge preserves tags, custom field values, tasks, notes, activities, external references, and emits `record.merged` audit events.
- Agent-oriented workflows: deterministic record enrichment, scored/verifiable next actions, workflow proposals that can be approved, applied, dismissed, or rejected, automation rule storage, automation-generated proposals without automatic application, and account briefs generated from CRM data.
- Small JSON/CSV import preview and commit for leads, accounts, contacts, deals, activities, tasks, and notes, including column mapping and per-row validation errors.
- JSON export through the app service and export hook, with lifecycle import round-trip support for complete CRM export payloads through service, CLI, and MCP schemas. Export includes active and archived records plus active external refs, preserves `archived_at` on import, and intentionally omits soft-deleted records and unlinked external refs. Export is not capped by the interactive list limit.
- Active records cannot link to archived parent accounts, contacts, or deals. Archived records may preserve historical links to archived parents during CRM export imports.
- Dense operational UI with primary Records, Pipeline, and Reports entry points, shell/widget navigation handling, SQL-backed records table pagination/sort/filter with stable opaque cursors and batched computed fields, shared record side panel, lead conversion, record tag/archive/delete actions, bulk tag/archive, saved view controls, timeline display, audit event display with entity/action/date filters, linked-item display/manual linking/unlinking, custom field display, enrichment proposal creation, account brief generation, next-action suggestions, dedupe review, a compact agent deck embedded above the Pipeline board, persisted search filter rendering, custom view rendering with referenced-record hydration, footer widget create-menu intent handling, create chooser and create/edit composer forms, and import preview before commit.
- Health checks covering schema metadata, SQLite integrity, FTS coverage, orphan CRM references, active children linked to archived parents, view state validity, export/archive-import consistency, orphan custom field values, workflow proposal action validity, external reference malformation/unresolved status, and exportability.
- Base-shell sidebar and sidebar footer widgets.

The `crm.records_table` backend action is intentionally app-owned UI infrastructure for the Records view. `crm.operations_feed` follows the same pattern for the Pipeline agent deck, aggregating open tasks, workflow proposal lifecycle buckets, and recent relevant audit events into UI-ready sections without exposing a separate Operations page. These helpers are covered by service tests and listed in the operations manifest, but they are not declared as new MCP/CLI capabilities because they do not yet need to be agent-facing public surfaces. Saved views, persisted view state, custom-field definition administration, and direct automation-rule execution follow the same governance split: they remain backend/CLI actions for the frontend and operators, while MCP exposes the smaller stable agent-facing surface declared in `app_contract.json` and `mcp/tool_schemas.json`.

Deferred intentionally:

- Live external CRM sync.
- Persistent import job queues.
- Deep permission model beyond platform workspace enablement.
- AI scoring or automation execution that cannot be deterministically verified.

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

## Verification

Frontend behavior is covered by Playwright tests with a mocked CRM backend:

```bash
npx playwright install chromium
npm run test:e2e
```

The suite exercises cockpit routing, record-table pagination, filters, saved views, bulk actions, and desktop/mobile screenshot capture.
