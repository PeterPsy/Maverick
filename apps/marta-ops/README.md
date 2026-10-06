# Marta Ops

Marta Ops is the operational workspace for Marta Giunti and her team. Version 0.6 completes the focused Mail, Calendar and Storage workflow around each collaboration.

## Product scope

- **Oggi** brings together urgent work, upcoming deadlines, follow-ups, pipeline totals and recent activity. Outstanding invoices remain visible after a collaboration closes.
- **Lavori** offers a Kanban pipeline and a searchable list, with filters by status, kind and phase. Each column shows its count and value. Cards can be moved using mouse/touch drag, keyboard drag, or their phase selector; ordering and phase changes are persisted.
- **Consegne** flattens deliverables across every work item into one status board. It highlights overdue and near-term delivery dates, supports work and text filters, changes status in place, and opens the owning work directly on its delivery tab.
- **Contatti** stores brand/agency representatives, their details and tags, linked work, follow-ups, notes and history. Archiving a contact retains its relationships.
- **Attività** tracks tasks, calls, emails and meetings with deadlines and optional contact/work links. Tasks can be completed, reopened and edited.
- **Amministrazione** derives a compact control list from work values, payment states, contract states and rights expiries. It supports in-place updates but deliberately does not implement invoices, tax, bookkeeping or payment processing.
- **Idee** retains the lightweight editorial inbox.

Work panels keep details, deliverables, tasks and timeline in separate tabs. Unsaved fields survive unrelated data refreshes and failed requests. Contact and task creation use focused drawers with keyboard focus handling. All screens use the app-owned Maverick tokens and responsive layout.

## Atomic CRM adaptation

Reference: [Marmelab Atomic CRM](https://github.com/marmelab/atomic-crm/tree/a863e2a084fae8c7adf7a2efc547ad7ce38e699b), pinned to commit `a863e2a084fae8c7adf7a2efc547ad7ce38e699b`.

The phase grouping and Kanban component structure are adapted from `deals/stages.ts`, `DealListContent.tsx`, `DealColumn.tsx` and `DealCard.tsx`. Contacts, notes/timeline and task completion follow Atomic CRM's corresponding flows. The UI uses the same drag-and-drop library and Radix dialog primitives, with local components and Maverick styling. The MIT attribution and complete license are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); the served artifact includes `atomic-crm-license.txt`.

Marta Ops continues to use Maverick's authentication, hosting and app-owned JSON backend. It does not require Atomic CRM's Supabase, Docker, react-admin infrastructure or separate authentication. It does not add a second mailbox, calendar, file archive, client portal or accounting system.

## Maverick sidebar and events

The app owns its native Maverick sidebar with compact Oggi, Lavori, Consegne, Contatti, Attività, Amministrazione and Idee rows. Badges count overdue unpublished deliverables, unfinished tasks and invoiced/overdue work awaiting payment, including completed collaborations. Only overdue deliveries and overdue payments use the attention color. The read-only `sidebar_summary` backend action returns five integer counts, without records or integration metadata, and uses the validated `today` date supplied by the client to match the full app's local-day deadline rules. Sidebar counts refresh on app events, reconnect, document visibility and local-day changes; failed reads hide counts and expose retry.

**In ritardo**, **Da approvare** and **Da incassare** open the matching delivery or payment filter. Quick-filter navigation clears conflicting search/work filters. Manual section filters, board/list mode and per-section search stay in memory for the current app mount and reset on workspace remount; they are never written to browser storage. The app mirrors its active section/filter through the generic `maverick.app.selection-changed` protocol, so sidebar selection follows manual filter changes without reloading. Live widget context takes precedence over a late initial read, and layout-only context updates preserve the latest app selection. Context failures expose retry.

The footer and mobile shell primary action create a contact in Contatti, a task in Attività, focus idea capture in Idee, and create work elsewhere. Creation uses unique request ids to avoid replaying a request. Inside Maverick, the app header contains the current section, search and create action; section menus belong to the shell sidebar. Standalone previews retain the app's desktop and horizontally scrolling mobile section menus. Selecting a destination closes the mobile sidebar.

The app and both widgets apply shell dark/light theme parameters before first paint and accept live theme updates only through the exact-parent message contract. Theme changes update app-owned tokens without remounting frames.

The shared SDK resolves the Core-injected local app binding and validates the exact shell parent for navigation messages. Data updates use the SDK's app event transport, including isolated frames and reconnects. Frontend builds use the standard Maverick asset manifest and isolated-frame asset URL plugins. No app data is persisted in browser storage.

## Mail, Calendar and Storage

Each existing work exposes one compact integration area:

- **Mail** selects one connected account, saves current work fields, and creates or updates the same partner draft. Linked Storage documents are added as workspace attachments. Marta Ops never sends the message.
- **Calendar** selects one writable Google calendar and creates or updates the same all-day deadline event. Its provider id and revision are retained to avoid duplicates and stale updates.
- **Storage** opens the native local-file picker, validates the returned file through Storage, and links only its stable metadata to the work. Opening a document returns to Storage; unlinking it does not delete the original file.

Available accounts and calendars refresh automatically when stale and can be refreshed manually. Marta Ops stores only bounded, redaction-safe connection labels, user preferences, and resource references. The integrations use declared optional app interfaces (`mail.workspace`, `calendar.events`, and `file.catalog`) through Maverick's governed dependency backend and callback surface; no other app's private store is accessed.

## Owned data

Data lives in `data/marta-ops/state.json` through the SDK's atomic update helper. The envelope contains collaborations, ideas, contacts, tasks, an activity timeline, integration preferences and stable external references (schema 3).

Schema 1 work and idea records are retained. Missing collections and contact/order fields receive additive defaults in memory and are written only with the next explicit mutation. Bootstrap never rewrites existing data. Kanban moves anchor against the complete destination column so filtered-out cards retain their order. A stale source phase is rejected before any write. The timeline stores plain-text notes and successful record changes; it is an operational history, not a security audit log. Existing records do not receive invented historical events.

## Verification and registration

From the app root:

```bash
PYTHONPATH=../../../.. python3 -m unittest discover -s tests -p 'test_*.py'
npm ci
npm test
npm run build
```

From a current authenticated Maverick runtime:

```bash
maverick core cli run core.app-sdk.validate --app-id marta-ops --json
maverick core cli run core.app-sdk.register-local --app-id marta-ops --json
maverick core cli run core.app-sdk.install-local --app-id marta-ops --json
maverick app marta-ops frontend build --json
maverick core cli run core.app-sdk.status --app-id marta-ops --json
```

Backend tests cover old-data retention, validation, contact links, task completion/reopening, notes, sparse and filtered pipeline ordering, governed callbacks, draft/event reuse, verified Storage attachments and read-only sidebar counts/date validation. Frontend tests cover record editing/failure recovery, contact autofill, phase changes without dragging, task relationships, delivery status changes, administrative updates, integration controls, Storage picker returns, stacked-drawer saves, exact shell origin checks, refresh races, sidebar context failures, live badges, quick filters, retained section state, contextual footer/header actions and theme messages. Browser preview verification uses synthetic records with the real app backend in a temporary data root; it does not read or seed the workspace's production data.
