# CRM product and visual alignment

Date: 2026-09-19

## Product decision

The user requests the closest practical match to the reference CRM, retaining
Maverick's colors. Reference: `PeterPsy/versy-crm` at
`43ee8870185c4a3f399c8db598d960ad809f09e0` (local read-only source review).
This replaces the earlier loose visual inspiration with an explicit screen and
interaction comparison. No production Versy data, credentials or services are
required. Existing Maverick records, IDs, links and integrations remain intact.

## Native implementation plan

1. Compare the reference shell and each generic view using source and a local,
   read-only fixture render; never connect the reference renderer to production.
2. Replace the horizontal navigation with the reference's persistent sidebar,
   compact search/action bar and mobile navigation. Dashboard is the landing page;
   established record deep links and the advanced record table remain available.
3. Align dashboard, tasks, threads, people, companies, deals, expenses, calendar,
   intelligence, brief/transcript review, proposals and data-quality surfaces.
   Reuse existing record mutations and the approved provider-operation workflow.
4. Use bounded, live-only CRM read models for cross-record operational views.
   Do not enlarge offline caches, query provider databases, migrate schema/data,
   automatically send mail or invent missing metrics/summaries.
5. Verify real Python-backed browser flows, responsive screenshots, existing
   backend contracts, official frontend build, and unchanged live business data.

## Deliberate differences from the source

- Maverick theme variables only; no Versy logo, palette switch or owner identity.
- Generic accounts/custom objects replace real-estate and presentation domains.
- Existing campaign planning is retained but excluded from this new port and from
  delivery/integration work. No technical ticket board is embedded in CRM.
- Mail, Calendar, Storage, Speech and Checklist own external effects. Calendar
  lists linked event snapshots with provenance/freshness; it is not a replicated
  external calendar. Mail delivery remains explicitly reviewed in Mail.
- Data-quality suggestions and transcription follow-ups require approval. A
  source's automation badge is never copied unless the capability actually exists.
- Currencies are never summed together. Empty states represent actual empty data,
  not seeded competitors, fabricated weekly briefs or invented commercial scores.
- The advanced records table, import/export, configurable pipeline and existing
  public surfaces remain available even where the reference has no equivalent.

Implementation and verification results are recorded below with the release.

## Delivered screen comparison (0.7.0, schema 8 unchanged)

| Reference surface | Native implementation | Intentional boundary |
| --- | --- | --- |
| 224px sidebar, search/action bar | Persistent sidebar, shared shell-widget navigation, mobile drawer, Ctrl/Cmd-K search, refresh/create | Maverick branding/theme, no source workspace/identity or theme switch |
| Dashboard | Brief selector, joined KPIs, full-width value/margin stage chart, next tasks, recent people/threads and active deals | Separate currencies; existing configured stages; no invented brief or score |
| Task periods and category accordions | Today (including overdue), 1–7 / 8–30 days, undated/all, open/completed, category/priority groups, complete/reopen | Explicit record metadata, not language-specific keyword inference |
| Thread queues | Reply/waiting/completed, state changes, record inspector with participants, links and connected work | Canonical Mail/provider identities remain external |
| People / companies | Dedicated person table, company cards, live relationship counts, search/order/pagination, retained list behind inspector | Advanced filters/custom fields remain in Records; no fabricated contact stages |
| Deals | Value/margin/close-date table, inline stage changes, contextual links, existing Kanban/operations | Existing configurable stages and record IDs retained |
| Expenses | Currency-separated totals, dated movements, supplier/category, decimal amount entry, Storage receipt context | Persisted integer minor units are unchanged |
| Calendar | Date-range agenda, provider links, freshness/errors, meeting-context entry to approved scheduling, briefing and outcomes | CRM-linked snapshots only; day/7-day/30-day/all rather than a replicated provider calendar |
| Competitive research / briefs | Generic intelligence cards, review dates, brief archive and linked context | No sector seeds, crawlers or scheduled AI worker claims |
| Data quality / proposals | Missing-email/domain review, duplicate candidates/merge review, exact preview, separate approval/application | No automatic enrichment/merge; latest 200 proposals, up to 100 duplicate groups explicitly labelled |
| Transcriptions | Speech journal list/detail, result/error state, original CRM context and note-proposal review | Audio stays in Storage; provider configuration/approval still required |
| Settings | Existing selected-provider Connections surface and workspace Settings | No private credentials copied into CRM |

The source shell/dashboard were rendered locally with a synthetic person and no
provider calls. Server actions and out-of-scope Sales/Tech/Campaign components
were replaced only in the temporary reference harness, not in either repository.
The source's layout/CSS and generic flows were also inspected directly. Native
Chromium screenshots cover desktop/mobile layouts and connected work. This is
structural and interaction alignment, not a claim of identical backend services
or pixel-perfect parity.

## Read-model contract and preservation

`crm.workspace_view` is an app-owned, live-only read helper listed in
`operations.manifest`, alongside the existing Records/Operations helpers. It has
no write events, new public MCP/CLI surface, provider effects or persistent-cache
allowlist. Views use a closed entity catalog, parameterized queries, active-record
filtering and bounded pagination (1–100, UI pages of 40). Search/range filtering
precedes pagination. Expense totals cover all matches, separately by currency.
Calendar rows preserve each CRM relationship to an event; the same event linked
to two records is deliberately two context rows. Empty, stale and failed states
are shown instead of silently dropping evidence.

No migration, database replacement, source import, provider reselection or
campaign delivery was performed. A read-only comparison with the prior schema-7
backup found 34 business tables identical, including all 15 external references.
The remaining differences are the existing deal's stage/probability and three
`deal.moved` audit events at 19:29 UTC on 2026-09-19; they were retained, not
reverted to the older backup. SQLite integrity is `ok`. Production fixture data
was never created by the new tests; browser tests use temporary isolated stores.

## Release verification

- 118 Python tests passed, including bounded queries, currency totals, timezone
  and date-only task boundaries, calendar pagination, read-only review and existing
  import/migration/integration regressions. The suite still emits an existing
  non-fatal SQLite `ResourceWarning` in connection-summary coverage.
- 20 Chromium browser tests passed with one worker, including real isolated
  Calendar/Storage approval flows, legacy navigation/bulk/merge/import coverage,
  new operational screens and thread state transitions. The five product tests
  were rerun successfully after the final responsive CSS adjustment; the mobile
  test checks actual search/control bounds, not only document overflow.
- TypeScript, unused-import check and Git whitespace checks passed. SDK validation
  reports no issues. Official frontend build completed and emitted the core app
  refresh event; runtime discovery reports `crm` version `0.7.0`.
- Live health reports healthy schema 8 and SQLite integrity `ok`. Selected Mail,
  Calendar, Storage (catalog/preview/write), Speech and Checklist dependencies
  remain resolved. Previously unresolved imported references remain preserved;
  they are not relabelled as verified provider records.
