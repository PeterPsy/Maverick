# CRM vNext: native, generic, additive

Date: 2026-09-19

## Decision and compatibility

`apps/crm`, `app_id=crm`, and `crm.records` remain the single CRM. The product
reference is `PeterPsy/versy-crm` at
`43ee8870185c4a3f399c8db598d960ad809f09e0`, reviewed alongside Chat's
“Accesso repository GitHub account giuntiocram”. No upstream runtime, branding,
owner identity, authentication, credentials, scraper, or seed data is bundled.
Python/SQLite, React/Vite, existing record IDs, public actions, provider selections,
workspace data roots and website-intake connections remain authoritative.

The user's explicit data-preservation requirement is the written compatibility
decision for the existing CRM surfaces. Existing customer-specific intake behavior
is retained, not applied as a default for new CRM domains or imported records.

## Implementation sequence and release gates

1. Capture current export and health; implement an additive schema migration and
   test it on isolated copies. Never move, replace, truncate, or reseed business data.
2. Introduce generic conversations, campaigns (variants, steps, members, events),
   expenses, briefs, intelligence profiles and typed custom objects. Reuse tasks,
   activities, notes and approvable workflows instead of duplicating these domains.
3. A single typed `record_links` graph represents participants, thread links,
   deal relationships and campaign context. It replaces redundant thread-specific
   link tables and validates both ends. External records stay in `external_refs`.
4. Add bounded import planning and apply as separate actions: use the same writer
   against an isolated database for simulation, fingerprint the source and target,
   fail closed on stale plans, preserve source identity, record per-row outcomes,
   and roll back the entire batch on any error. No automatic fuzzy merge.
5. Expose operational UI and declared CLI/MCP/reference/event surfaces. Campaign
   planning is not campaign delivery. Provider operations retain their own approval
   boundary and CRM cannot infer authorization to send from an imported status.
6. Validate backend, contracts, UI build and data preservation; commit only CRM
   source, its tests/artifacts and this decision. Do not restart shared backend or
   modify other agents' work merely to publish app-only changes.

## Import and integration boundaries

Native CRM exports remain supported. Generic CSV/JSON and an explicit Versy
adapter normalize external identities, dates, cents, relationship arrays and
industry-specific fields. Vertical objects are user data, never built-in product
assumptions. Source-only fields are retained as provenance, except secrets and
ephemeral integration/cache/job state. Unknown tables must be reported, not dropped
silently. Manual conflicts are reported for review, not automatically executed.

Small batches are atomic, not partially committed. Larger migrations must use
explicit, ordered, independently validated batches; this release does not pretend
to provide a detached import queue or distributed transaction across apps.

Mail, Calendar, Storage, Speech and Checklist are optional interface-selected
providers. CRM stores lightweight references; it never reads their private SQLite
files or copies tokens. Provider IDs must come from workspace dependency selection.
Legacy provider snapshots are unresolved migration evidence until matched to real
provider record identities. A provider outage must not erase a CRM link.

## External source data decision

The user explicitly excluded production Versy data and assets. No D1 export,
R2 inventory or Versy cutover is required. Preserve the existing Maverick business
data and connections. The optional adapter remains available for explicitly
supplied exports; fixtures do not imply migration of any production source.

## Initial release: 0.5.0 (2026-09-19)

Version 0.5.0 / schema 7 implements the generic domains, relationship graph,
typed forms/detail pages, overview/today workspace, selected-provider reference
linking, guarded synchronous imports, source adapter, CLI/MCP contracts and native
export restoration. Existing records, pipeline, reports, website intake and
approvable workflows remain available. Speech and Checklist requirements are
optional and do not auto-select providers.

Verification: 88 Python tests, 13 Chromium browser tests (including isolated real
Python backend flows), TypeScript, unused-import check, SDK contract validation,
official frontend build and desktop/mobile visual review passed. The live schema-6
backup passed SQLite integrity checking. Every pre-existing business table was
compared, column-for-column and row-for-row, against the migrated database: records,
archived/deleted data, events, intake receipts, notification outbox and all 15
external references remained unchanged. Live health reports healthy schema 7;
Mail, Calendar and Storage selections remain available.

This is not a claim of complete production Versy parity. The subsequent 0.6.0 /
schema 8 integration release adds approved Mail/Calendar/Storage/Checklist/Speech
operations, targeted reference synchronization and meeting workflows, documented in
[CRM operational integrations](crm_integrations_architecture.md). Campaign
integration/delivery and scheduled competitive crawling remain excluded. Existing
provider apps own external effects; no Versy production import is needed.


## Product alignment release: 0.7.0 / schema 8

The subsequent [product-alignment decision](crm_product_parity.md) replaces the
loose visual inspiration with a source-compared sidebar/dashboard and dedicated
operational screens, while retaining Maverick colors, existing records and
provider boundaries. It introduces bounded live-only UI reads, not a migration,
new cache authority, campaign delivery or a second CRM.
