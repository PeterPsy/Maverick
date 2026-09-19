# CRM

Native, generic Maverick CRM, version 0.7.0 / schema 8. One app (`crm`), one interface (`crm.records`), and one workspace-owned database: relationships, sales, conversations, follow-ups, campaign planning, expenses, intelligence, typed custom objects, import/export, and approvable agent workflows.

The implementation is native Python/SQLite and React/Vite. External CRM projects informed the domain and UX direction; no Cloudflare, Vinext, Ably, external authentication, industry-specific branding, owners, or seed data are bundled. CRM behavior stays app-owned; the core validates, registers, mounts, and invokes declared contract surfaces. See [the vNext decision](../../docs/architecture/crm_vnext_architecture.md) for source provenance, compatibility, and release boundaries.

## Repository Model

This is a forkable platform app source tree versioned under the installation-level Maverick `apps/crm/` directory.

Track app source, tests, contract files, and intentional frontend build artifacts here. Do not track workspace data such as `data/crm/crm.sqlite`, generated caches, `node_modules/`, or Python bytecode.

## Surfaces

- Frontend: `frontend/dist`, rebuilt from React/Vite sources under `frontend/src`.
- Backend: `backend/app_backend.py`, invoked through `/api/apps/crm/backend`; the service router delegates larger domains to `backend/domains/`.
- CLI: `crm`, described by `cli/command_schemas.json`.
- MCP: a stable agent-facing subset for search/read, lead/account/contact/deal CRUD, website intake ingestion, task/note/activity creation and updates, deal movement, record archive/delete/tag/bulk/merge, timeline/audit/report/filter/dedupe, external references, typed custom field value reads/writes, deterministic enrichment, next actions, workflow proposal approve/apply/dismiss/reject lifecycle, account brief, import/export, reference resolution, standard CRM view-state actions, and health. Saved views, custom-field definition management, and automation-rule administration stay backend/CLI helpers rather than public MCP tools.
- Widget: `crm-sidebar` for the `base-shell` primary sidebar slot.
- Lifecycle hooks: install, migrate, export, import, health check and bounded background reference refresh.
- Skill template: `skills/crm-ops/SKILL.md`.

## Storage

CRM data lives only under the workspace app data root:

```text
data/crm/
  .maverick-app.json
  crm.sqlite
  view_state.json
  backups/schema-<previous>-before-<next>-<unique-id>.sqlite
```

The SQLite schema is initialized idempotently by install and migrate hooks. The current release includes leads, accounts, contacts, deals, configurable pipelines, pipeline stages, activities, tasks, notes, website intake receipts, CRM notification outbox rows, events, tags, record tags, saved views, typed custom field definitions/values, automation rules, workflow proposals, external reference snapshots, and an embedded FTS index. Task and note records are first-class service, MCP, CLI/import, reference, and frontend entities. Archive, soft-delete, tag, untag, bulk operations, lead conversion, saved views, timeline, audit log, native sales reports, duplicate discovery and merge, typed custom fields, deterministic enrichment, approvable workflow proposals, automation proposal generation, external reference linking, and import row validation are exposed through backend, CLI/MCP where appropriate, and the operational UI. The app does not store raw secrets; external connectors use selected provider apps and core secret grants.

Migration first takes a consistent, integrity-checked SQLite backup. Schema 8 adds an integration-operation journal; existing IDs, records, references, pipelines, field definitions, and provider selections remain in place. A newer database is never silently downgraded. Do not replace the live SQLite file to upgrade the app.

## Existing capabilities retained

Included:

- Lead, account, contact, deal, activity, task, and note persistence.
- Website intake ingestion through `crm.website_intake`: creates an idempotent lead from a public form submission, assigns the lead to `Peter.fioretti94@gmail.com`, persists the normalized payload in `website_intakes`, creates retryable `crm_outbox` notification rows, sends Mail notifications through the selected `mail.workspace` provider, and links resulting Mail refs back to the lead.
- Lead conversion into account, contact, and optional deal records.
- Configurable sales pipeline stages with drag/drop deal movement in the UI.
- Search, record lookup, account summary, and next-action listing for open tasks only.
- Timeline retrieval for account, contact, deal, and lead records.
- External reference snapshots for linking CRM records to provider records through declared CRM surfaces only. CRM stores `source_app_id`, source entity identity, link type, normalized `provider_alias`, `source_interface`, title, summary, occurrence time, and metadata; it does not read provider private data.
- Optional app-link requirements for Mail (`mail.workspace`), Calendar (`calendar.events`), Storage (`file.catalog`, `file.preview`, `file.content.write`), Speech (`speech.transcription`), and Checklist (`checklist.task`) let workspace Settings select concrete providers. Existing selections are not changed by migration. Unselected optional providers remain visibly unconfigured.
- Typed custom fields with schema/config discovery, validation, record values, filtering support, export/import round trip, and frontend detail rendering.
- Saved views, advanced local filters, bulk tag/archive actions, and duplicate detection for account/contact/lead email/domain data.
- Native sales reports for pipeline value by stage, weighted forecast, deal aging, lead conversion, overdue tasks, and activities by owner.
- Merge dedupe for leads, accounts, and contacts. Merge preserves tags, custom field values, tasks, notes, activities, external references, and emits `record.merged` audit events.
- Agent-oriented workflows: deterministic record enrichment, scored/verifiable next actions, workflow proposals that can be approved, applied, dismissed, or rejected, automation rule storage, automation-generated proposals without automatic application, and account briefs generated from CRM data.
- Small JSON/CSV import preview and commit for leads, accounts, contacts, deals, activities, tasks, and notes, including column mapping and per-row validation errors.
- JSON export through the app service and export hook, with lifecycle import round-trip support for complete CRM export payloads through service, CLI, and MCP schemas. Export includes active and archived records plus active external refs, preserves `archived_at` on import, and intentionally omits soft-deleted records and unlinked external refs. Export is not capped by the interactive list limit.
- Active records cannot link to archived parent accounts, contacts, or deals. Archived records may preserve historical links to archived parents during CRM export imports.
- Dense operational UI with primary Records, Pipeline, and Reports entry points, shell/widget navigation handling, SQL-backed records table pagination/sort/filter with stable opaque cursors and batched computed fields, shared record side panel, lead conversion, record tag/archive/delete actions, bulk tag/archive, saved view controls, timeline display, audit event display with entity/action/date filters, linked-item display/manual linking/unlinking, custom field display, enrichment proposal creation, account brief generation, next-action suggestions, dedupe review, a compact agent deck embedded above the Pipeline board, persisted search filter rendering, custom view rendering with referenced-record hydration, create chooser and create/edit composer forms, and import preview before commit.
- Health checks covering schema metadata, SQLite integrity, FTS coverage, orphan CRM references, active children linked to archived parents, view state validity, export/archive-import consistency, orphan custom field values, workflow proposal action validity, external reference malformation/unresolved status, and exportability.
- Base-shell sidebar widget.

The `crm.records_table` backend action is intentionally app-owned UI infrastructure for the Records view. `crm.operations_feed` follows the same pattern for the Pipeline agent deck, aggregating open tasks, workflow proposal lifecycle buckets, and recent relevant audit events into UI-ready sections without exposing a separate Operations page. These helpers are covered by service tests and listed in the operations manifest, but they are not declared as new MCP/CLI capabilities because they do not yet need to be agent-facing public surfaces. Saved views, custom-field definition administration, and direct automation-rule execution follow the same governance split: they remain backend/CLI actions for the frontend and operators, while MCP exposes the smaller stable agent-facing surface declared in `app_contract.json` and `mcp/tool_schemas.json`, including the standard view-state tools required by the CRM view surface.

## vNext operational workspace

- **Dashboard:** reference-aligned sidebar and search bar, brief archive selector, joined financial KPIs, full-width value/margin pipeline chart, next tasks, recent people/threads and active deals. Maverick theme colors only; no seeded business data.
- **Tasks:** local-time Today / 1–7 days / 8–30 days / undated queues, category or priority groups, completion/reopening and contextual inspector.
- **People / Companies / Deals:** dedicated person table, company cards and deal table with inline stage movement, value and margin. Non-modal right inspectors retain the originating list. Advanced Records, Kanban/Pipeline, reports and import remain under Workspace tools; established record deep links are retained.
- **Threads:** To reply / Waiting / Completed queues with explicit state transitions. Native threads link participants, tasks, deals and provider references through the existing validated relationship graph.
- **Calendar:** date-filtered agenda of CRM-linked Calendar snapshots, explicit verification/failure state, provider links and scheduling/meeting context. Not a copy of the entire external calendar.
- **Proposals / Data quality / Transcripts:** separate review queues, validated preview before approval/application, missing-field and duplicate review, Speech operation history and reviewable note context.
- **Campaigns:** draft/ready/paused/completed planning, variants, ordered steps, recipients and event history. Cross-campaign references and duplicate recipients are rejected. These operations do **not** send, schedule workers, or authorize provider delivery.
- **Expenses / Intelligence:** expenses, competitive profiles and periodic/meeting briefs, with typed dates, metadata, ownership and linked records.
- **Custom objects:** user-defined typed schemas and records. Vertical source objects are imported as optional user data, not built-in real-estate concepts.
- **Connections:** current selected-provider identities and linked counts. CRM detail pages search and verify Mail threads, Calendar events, Storage assets and Checklist records through the core-governed provider backend. Verified snapshots refresh in bounded batches; failures retain the last good context. Speech processes linked audio and returns reviewable transcript proposals, not reference entities. No private provider database or credential is read.

New MCP/CLI actions include `extension_schema`, `list_extension_records`, `create_extension_record`, `update_extension_record`, `link_records`, `unlink_records`, `record_context`, `overview`, `integration_context`, `link_provider_record`, `import_plan`, `import_apply`, and `import_jobs` (CLI prefix `crm.`, MCP prefix `crm_`). New entities also participate in search, references, custom fields, lifecycle, audit and native export/import. The bounded, read-only `crm.workspace_view` helper supplies task/thread/expense/brief/intelligence/calendar/transcript/quality screens. Like the existing Records and Operations helpers, it is UI infrastructure, not a new public CLI/MCP action. New views use live reads; this release does not expand the reviewed offline/PWA data allowlist.

See [CRM product alignment](../../docs/architecture/crm_product_parity.md) for the pinned upstream comparison, screen matrix and deliberate native differences.

## Operational app integrations

Every non-campaign record has **Connected work**:

- **Mail:** search and connect real threads/messages/drafts/attachments; prepare a new message or reply, optionally with verified Storage attachments. Approve and execute to create a draft, then open Mail to review and explicitly send. CRM does not send mail or run campaigns.
- **Calendar:** create native Maverick meetings with timezone-aware times, attendees, CRM context and provider idempotency keys. External Google invitations are not implicitly created. Existing linked provider events can be resolved and refreshed.
- **Storage:** search/link documents and audio; create a Markdown document, optionally prefilled with the CRM meeting brief. Storage owns paths and file writes.
- **Checklist:** connect a real checklist, propose a task in an existing section, and propose status changes. The task remains canonical in Checklist, not an editable duplicate CRM task.
- **Speech:** transcribe an explicitly linked local Storage audio file using the selected provider's configured engine. The resulting text is a separate note proposal requiring review, approval and application. No transcript can authorize subsequent actions.
- **Meetings:** deterministic briefing from CRM context and linked snapshots; record human-supplied outcomes as activities and follow-up proposals with idempotent submission. Applied follow-ups stay linked to their contact, deal or generic conversation context.

New public actions: `integration_prepare`, `integration_run`, `integration_retry`, `integration_search`, `integration_link`, `integration_reconcile`, `integration_get`, `integration_list`, `integration_refresh`, `meeting_brief`, `meeting_outcome`. Read-only receipts/briefs and mutating preparations/execution have distinct effects. Callback and tick actions are private trusted-core surfaces, not CLI/MCP tools.

Execution follows **prepare → inspect exact request → approve → execute**. Provider selection is checked again at execution; the immutable request cannot be edited after approval. Claims prevent concurrent/replayed execution. Uncertain non-idempotent writes cannot be blindly retried: verify an existing provider identity and reconcile it instead. Calendar retries reuse the provider idempotency key. Speech failures require checking Speech before preparing a new operation.

Background ticks refresh up to five opted-in links, due every five minutes; manual refresh handles up to ten links. Trusted linked-provider UI events trigger a debounced refresh of the visible CRM record. This is targeted snapshot synchronization, not provider-wide replication or two-way editing. Legacy links are not automatically opted in: explicit refresh or verified reconnection enables synchronization. Missing remote records never delete CRM records.

Operation receipts export as history. Restoring them cannot restore execution authority or edit a local operation's approval. Records with receipts cannot be deleted or merged, and running operations prevent archive, protecting their immutable context. Resolve/reconcile running work before archiving. See [integration architecture](../../docs/architecture/crm_integrations_architecture.md).

## Reviewed imports

The Import UI accepts CSV, JSON rows, native CRM exports and external table exports through the Versy adapter. CSV supports explicit column mapping. The public `crm.import_plan` action uses an isolated database copy and the **same writer** as `crm.import_apply`; it does not create records, jobs or view-state changes in the live CRM. Apply requires its returned `plan_token` and rejects a changed source, policy or target database. Every batch is atomic; any invalid row or relationship rolls back all its changes. Successful imports persist reports, per-row outcomes and stable source identities. Replaying the same applied plan is harmless.

Limits: **8 MB and 2,000 records/relationships per batch**, including derived records. Larger source migrations require ordered, independently reviewed batches. Use the same `source_id` for subsequent batches/imports; supply stable `id` or `external_id` values. Rows without either use a content fingerprint, so edited rows cannot be recognized as the same source identity automatically.

Conflict policies: `skip`, `duplicate` (still idempotent per source identity), `fill_empty`, `overwrite` (supplied fields), and `manual` (stop for explicit review). Only unique exact email/domain matches are deduplicated; no fuzzy merge is automatic. Native restore requires explicit `overwrite` and preserves source IDs. Legacy `import_preview` / `import_commit` remain for existing integrations; use plan/apply for the new guarded workflow.

Example backend/CLI payload for `crm.import_plan`:

```json
{
  "source": {
    "format": "json",
    "source_id": "customer-system-production",
    "entity_type": "contact",
    "rows": [{"external_id": "person-1", "display_name": "Ada", "email": "ada@example.test"}]
  },
  "conflict_policy": "fill_empty"
}
```

Apply the identical payload with the returned `plan_token`. Inspect `crm.import_jobs` for successful receipts. Failed simulations report errors without creating a persisted job. Native business exports intentionally omit soft-deleted rows and their source identities; use the SQLite backup when deletion history/complete receipts must be preserved.

### External source adapter

`scripts/read_external_sqlite.py <export.sqlite> --source-id <stable-source-id>` reads an explicitly supplied SQLite export in read-only mode, emits adapter JSON on stdout, and reports excluded tables on stderr. It never executes arbitrary SQL dumps or accesses production D1. Submit the result to import planning, not directly to the database. The utility rejects oversized sources instead of truncating them.

The adapter maps people/companies, activities, follow-ups, deals, conversations, campaigns, expenses, briefs and competitive profiles. Source-only fields are retained as redacted provenance; expenses and margins retain integer cents, while deal values use the existing CRM decimal-value representation. Real-estate agencies become accounts; listings/presentations become optional custom objects. Data-quality suggestions become pending proposals for **review tasks**, not trusted imported update/send commands. Provider snapshots remain evidence until matched to authoritative Mail/Calendar/Storage/Speech identities. Credentials, integration settings, caches and transient workers are excluded; unknown tables are reported.

Production Versy data and R2 assets are **not required and are not being migrated**, by explicit product decision. The adapter remains an optional generic import utility, not a release dependency.

Deferred intentionally:

- Live external CRM sync.
- Background import queues (synchronous committed-job receipts are implemented).
- Campaign delivery and campaign integrations; existing planning remains unchanged.
- Provider-wide replication, external calendar invitations and unreviewed automation execution.
- Scheduled AI brief generation or competitive crawling; deterministic meeting briefs and explicitly approved transcription are implemented, not a port of external workers.
- Deep permission model beyond platform workspace enablement.
- AI scoring or automation execution that cannot be deterministically verified.

## SDK Flow

```bash
maverick core cli run core.app-sdk.validate --app-root apps/crm --json
maverick app crm frontend build --json
maverick app crm cli list --json
maverick app crm mcp list --json
```

## Contract Notes

CRM declares sandbox compatibility, app-owned SQLite, frontend/backend/CLI/MCP surfaces, one sidebar widget, CRM reference entities, view-state actions, lifecycle hooks, and optional provider dependencies. Read/planning actions and mutating/apply actions have separate effect declarations. Existing website-intake customer configuration is preserved for compatibility; it is not a new CRM owner default.

## Verification

Run focused verification from the repository root:

```bash
python3 -m unittest discover -s apps/crm/tests -p 'test_*.py'
python3 scripts/check_unused_imports.py apps/crm
apps/crm/node_modules/.bin/tsc --noEmit -p apps/crm/tsconfig.json
```

Browser tests (from `apps/crm`) include existing UI transport fixtures and a real Python backend on isolated temporary databases:

```bash
npx playwright install chromium
npm run test:e2e -- --workers=1
```

The suites cover migration backups, data/reference fidelity, future-schema refusal, typed extensions, campaign integrity, archive lifecycle, exact dedupe/policies, read-only simulation, stale plans, replay, rollback, secret exclusion, export round trips, provider selection, callback forgery, concurrent delivery claims, uncertain writes/reconciliation, safe retry, failed-refresh preservation, secret preflight without execution, and real isolated Mail/Calendar/Storage/Checklist contracts. Browser tests cover routing, pagination, record linking, campaign planning, import application, approved Calendar/Storage execution, follow-up review, and desktop/mobile screenshots. No test writes to the live workspace database or sends real email.
