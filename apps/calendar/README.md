# Calendar

Calendar is a Maverick workspace app for event planning. It provides a launchable React/Vite frontend with month, week, day, and list views, plus an app-owned backend that persists events under the workspace data root.

## Contract Notes

Calendar declares a workspace frontend, app-owned backend, lifecycle hooks, MCP tools, CLI commands, and JSON storage under `data/calendar/state.json`.

The first agentic surface exposes:

- event CRUD through scoped MCP and CLI
- semantic event moving through `calendar_move_event`, including first-free rescheduling in a bounded window
- exact-window availability checks through `calendar_check_availability`
- free-time search through `calendar_find_free_time`
- compact event listing with filters and pagination
- conflict policies on create, update, and move: `allow`, `reject`, or `warn`
- idempotent creates with `idempotency_key` and optimistic concurrency through `expected_revision`
- status-aware availability: `confirmed` and `tentative` events block time, while `cancelled` events remain stored but do not block availability
- orchestration metadata on every normalized event: `timezone`, `location`, `organizer`, `all_day`, `created_at`, `updated_at`, `revision`, `source`, `external_refs`, `recurrence`, `reminders`, and `idempotency_key`
- event reference search, resolve, and summarize tools
- declared `event` reference entities with stable `app_page` and `/app/calendar/events/<event_id>` deep links
- a standard Calendar view surface for reading filters, curating event references, refining custom views, and showing conflict-only views
- frontend view-state sync so agent-set filters/custom views move the visible calendar to the matching day, week, month, or curated list
- bundled `calendar-ops` skill guidance for safe agent scheduling workflows
- descriptor sidecars at `mcp/tool_schemas.json` and `cli/command_schemas.json`
- Google Calendar OAuth connection setup, remote calendar source selection, sync, and disconnect using Core Secrets for client credentials and per-connection refresh tokens

Calendar also supplies account-tree and primary-action sidebar widgets. Their
display reads suspend when the sidebar, app or document is hidden. Reopening
coalesces a fresh read without replacing the already displayed account tree.

Pending Google connections represent short-lived OAuth attempts, not connected
accounts. They stay out of the account tree, account filters and event destinations
until authorization completes. Starting or completing OAuth and listing connections
prunes attempts whose ten-minute state has expired, while preserving other live
OAuth flows and established accounts. Reauthorizing an existing Google account
reuses its connection and removes the completed temporary attempt.

The main view cancels window, preferences, metadata and event-detail reads on
suspension, ignores late results and preserves current content. App-events owns
the single online resume refresh. Offline foreground views may still paint the
authorized cached event window; network-only preferences and account metadata
wait for connectivity. Accepted event edits and provider sync operations keep
their existing completion semantics.

## Surfaces

- Frontend: `frontend/dist`, mounted as the workspace app view.
- Backend: `backend/app_backend.py`, used by the frontend through `/api/apps/calendar/backend`.
- MCP: `mcp/server.py`, exposing scoped tools for event CRUD, moving events, availability checks, free-time search, and event references.
- CLI: `cli/app_cli.py`, exposing `calendar` and `calendar-reference` commands through the core-managed app CLI surface.
- Hooks: install, migrate, and health check create and validate `data/calendar/state.json`.
- References: Calendar declares `event` as a searchable, resolvable, summarizable reference entity. Reference payloads include `app_id`, `entity_type`, `entity_id`, `title`, `subtitle`, `summary`, `app_page`, `deep_link`, and `safe_fields`.
- View surface: Calendar declares the standard `calendar` view surface with `view_filter`, `set_view_filter`, `set_custom_view`, and `clear_custom_view` actions so references can open or curate event views through official surfaces. `set_view_filter` accepts `conflicts_only` for conflict-focused views and `preserve_custom` to refine a curated event set. The frontend reads that persisted state, listens for `view-state` data events, and shifts the active calendar viewport to the requested time window, conflict list, or curated event list.
- Skills: `skills/calendar-ops/SKILL.md` is declared through `capabilities.skills` and guides agents to use scoped Calendar MCP/CLI surfaces, avoid direct state-file access, resolve timezone ambiguity, and check availability before conflict-sensitive mutations.
- Google Calendar provider actions: `calendar_connections.list` and `calendar_connections.start_oauth` expose connection setup through agent surfaces. OAuth completion is backend-only because it writes the account refresh token through app-managed Core Secrets. `calendar_calendars.list` exposes known remote calendars, including empty calendars discovered during sync, and `calendar_calendars.select` controls local sync enablement per calendar. The independent `selected`, `sync_enabled` and `availability_enabled` settings control display, provider fetching and planning. Hiding or pausing sync preserves the mirror and its busy intervals. Only disabling availability excludes a calendar from conflict and free-time checks. `calendar_sync` reads enabled Google calendars and events into local Calendar state with per-calendar sync cursors. New calendars without an existing cursor use a bounded cache by default, from 365 days in the past to 730 days in the future, and can be overridden with `time_min`, `time_max`, or `sync_mode: "full_history"`. Existing cursors with Google sync tokens continue using incremental full-history sync unless the caller requests bounded mode. When event import would exceed Calendar's storage cap, Calendar still persists discovered calendar sources and a structured `calendar_sync_event_limit` cursor error so users can disable unnecessary calendars or narrow the sync window before retrying. Google-backed create, update, delete, and move operations are allowed only for Google calendars where the connected account has `owner` or `writer` access; read-only imported events remain visible but are not offered as editable local mutations. Accepted remote mutations update Google first and then mirror the accepted remote event locally; account-level Google creates default to the provider's `primary` calendar when no specific `provider_calendar_id` is supplied. `calendar_connections.disconnect` revokes the Google token delivered through the resource-scoped Core Secrets grant and disables the local connection record.
- Widgets: account tree and create/connect footer are mounted in the native shell sidebar. The tree uses `calendar_accounts.summary`, without downloading the event list.

Agent-facing discovery should use the workspace's installed local app id. The examples below use `<calendar_app_id>`; in the default workspace binding this is `calendar`.

```bash
maverick apps list --json
maverick app <calendar_app_id> mcp list --json
maverick app <calendar_app_id> mcp inspect calendar_operations_manifest --json
maverick app <calendar_app_id> mcp call calendar_operations_manifest
maverick app <calendar_app_id> cli list --json
maverick app <calendar_app_id> cli run calendar --json
```

The MCP tools are:

- `calendar_operations_manifest`
- `calendar_accounts.summary`
- `calendar_connections.list`
- `calendar_calendars.list`
- `calendar_calendars.select`
- `calendar_connections.start_oauth`
- `calendar_connections.disconnect`
- `calendar_sync`
- `calendar_list_events`
- `calendar_create_event`
- `calendar_update_event`
- `calendar_delete_event`
- `calendar_move_event`
- `calendar_check_availability`
- `calendar_find_free_time`
- `calendar_view_filter`
- `calendar_set_view_filter`
- `calendar_set_custom_view`
- `calendar_clear_custom_view`
- `calendar_reference_manifest`
- `calendar_reference_search`
- `calendar_reference_resolve`
- `calendar_reference_summarize`

The `calendar` CLI command supports `calendar_accounts.summary`, `calendar_connections.list`, `calendar_calendars.list`, `calendar_calendars.select`, `calendar_connections.start_oauth`, `calendar_connections.disconnect`, `calendar_sync`, `list`, `create`, `update`, `delete`, `move`, `check_availability`, `find_free_time`, `view_filter`, `set_view_filter`, `set_custom_view`, and `clear_custom_view`. The `calendar-reference` CLI command supports `references.manifest`, `references.search`, `references.resolve`, and `references.summarize`.

## Google Calendar Security Model

Calendar declares Google OAuth and Calendar API outbound access for `accounts.google.com`, `oauth2.googleapis.com`, `www.googleapis.com`, and `calendar.googleapis.com`.

Google OAuth client credentials are Core Secrets logical names scoped to the workspace:

- `google-oauth-client-id`
- `google-oauth-client-secret`

Per-account Google Calendar refresh tokens use the `google-calendar-refresh-token` logical name. Calendar declares that name under both `permissions.secrets.read` and `permissions.secrets.write`; OAuth completion returns app-managed `platform_secret_writes` so the core stores refresh tokens in Core Secrets instead of `data/calendar`. Descriptor `secret_selectors` mark that refresh token as resource-scoped with `resource_type: "calendar_connection"` and `resource_id_argument: "connection_id"` for disconnect and sync actions.

Create the Google OAuth client id and client secret values through a full-access admin Core Secrets or Vault secure-input flow. Do not put the raw values in source, fixtures, logs, shell history, or README examples. After the two Core Secrets exist, grant Calendar access by logical name:

```bash
maverick core cli run core.secret_grants.create --json --arguments-json '{"app_id":"calendar","logical_name":"google-oauth-client-id","alias":"calendar-google-oauth-client-id","actions":["app.backend"],"target_patterns":["maverick://app.backend/backend","maverick://app.backend/cli/calendar","maverick://app.backend/mcp/calendar-connections.start-oauth","maverick://app.backend/mcp/calendar-sync"],"reason":"Allow Calendar to start Google Calendar OAuth and refresh Google Calendar access."}'
maverick core cli run core.secret_grants.create --json --arguments-json '{"app_id":"calendar","logical_name":"google-oauth-client-secret","alias":"calendar-google-oauth-client-secret","actions":["app.backend"],"target_patterns":["maverick://app.backend/backend","maverick://app.backend/cli/calendar","maverick://app.backend/mcp/calendar-sync"],"reason":"Allow Calendar to complete backend OAuth callbacks and refresh Google Calendar access."}'
```

The `alias` values above are examples for already-created Core Secrets metadata, not secret values. Operators can use different aliases or `secret_id` values. Verify the recommended redaction-safe needs with:

```bash
maverick app vault cli run vault --json --action diagnose --workspace_id default --app_id calendar
```

Vault should report `google-oauth-client-id` and `google-oauth-client-secret` as workspace-scoped needs with `recommended_action: "add_value"`. It should report `google-calendar-refresh-token` as an app-managed `calendar_connection` resource need with `recommended_action: "complete_app_setup"`; Calendar writes that refresh token through OAuth completion instead of asking an operator to paste it manually.

Backend actions that need a specific connection token must request secrets through the app-backend delivery contract, for example:

```json
{
  "action": "calendar_sync",
  "connection_id": "cal_conn_<id>",
  "_app_secret_request": {
    "required": true,
    "selectors": [
      {
        "logical_names": ["google-oauth-client-id", "google-oauth-client-secret"]
      },
      {
        "logical_names": ["google-calendar-refresh-token"],
        "resource_type": "calendar_connection",
        "resource_id": "cal_conn_<id>"
      }
    ]
  }
}
```

The canonical OAuth callback page for browser redirects is:

```text
/apps/<calendar_app_id>/oauth/callback
```

The default Google OAuth request scopes are:

```text
https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.calendarlist.readonly openid email
```

Calendar requests offline access and prompts for consent so Google can return a refresh token for the connected account. The callback page should pass the OAuth `code` and opaque `state` to the app backend with `action: "calendar_connections.complete_oauth"`. This completion action is intentionally backend-only: CLI and MCP surfaces can start OAuth, but they do not expose completion because only the mounted backend response can return `platform_secret_writes` for Core Secrets persistence. The direct backend completion surface remains:

```text
POST /api/apps/<calendar_app_id>/backend
```

No Calendar source file, fixture, log, README example, or app-owned state file should contain raw OAuth client secrets or refresh tokens.

## Storage

The app owns JSON state under:

```text
workspaces/<workspace_id>/data/calendar/state.json
```

The state file stores `schema_version`, `events`, `view_filter`, `connections`, `calendars`, and `sync_state`. The current data schema version is `3`. Event timestamps are serialized as ISO 8601 strings and converted to `Date` objects by the frontend.

Event ids are generated by the Calendar backend. Mutating requests validate required title and time fields, reject events whose end time is not after the start time, and bound free-form strings and list fields before writing to `state.json`.

Events include a `status` field with `confirmed`, `tentative`, or `cancelled`; omitted status defaults to `confirmed`. Availability, conflict checks, and free-time search ignore cancelled and transparent events.

Every event is normalized with orchestration fields for agent workflows. Omitted `timezone` defaults to `UTC`, `all_day` defaults to `false`, `source` defaults to `calendar`, `revision` defaults to `1`, and legacy records missing `created_at`/`updated_at` receive stable timestamp defaults from their `startTime`. Create operations generate `created_at`, `updated_at`, and `revision: 1`; update and move operations preserve `created_at` while incrementing `revision` and refreshing `updated_at`. `external_refs` and `recurrence` are bounded JSON objects, while `reminders` is a bounded JSON array. Google-sourced event references may include `calendar_account_id`, `calendar_account_label`, `calendar_connection_id`, `provider_calendar_id`, `provider_calendar_access_role`, `provider_event_id`, `html_link`, `etag`, and `ical_uid`.

Schema `3` adds normalized Google Calendar preparation records while preserving existing events. `connections` stores `calendar_connection` records with provider, account metadata, status, scopes, timestamps, and a Core Secrets token resource pointer for `google-calendar-refresh-token`; it never stores refresh token values. `calendars` stores remote calendar/source metadata keyed by connection and provider calendar id, including independent local `selected`, `sync_enabled` and `availability_enabled` flags that are preserved when Google calendar metadata is refreshed. `sync_state` stores per-connection or per-calendar sync cursor records with sync/page tokens, bounded sync windows, status, timestamps, non-secret error text, and structured event-count diagnostics for capacity failures.

Create operations with an `idempotency_key` are replay-safe: a repeated create with the same key returns the existing event with `idempotent_replay: true` and does not emit a data-changed event. `idempotency_key` is create-only and cannot be changed by later updates. Update, move, and delete operations require `expected_revision`; when the stored event revision differs, Calendar returns HTTP 409 with `revision_conflict`, the expected and actual revisions, and a compact `current_event`.

Agent list operations support compact output and filters including `start_after`, `end_before`, `query`, `tags`, `category`, `attendee`, `offset`, `limit`, `profile`, and `include_description`. MCP and CLI list calls default to compact output capped at 50 events unless the caller supplies an explicit `limit`.

Calendar view-state operations persist under the same state file as `view_filter`. `set_view_filter` accepts `query`, `start_after`, `end_before`, `category`, `attendee`, `tags`, and `conflicts_only`. When `preserve_custom` is true and the current view mode is `custom`, Calendar keeps the curated `entity_ids` and references while updating the filter fields. `set_custom_view` accepts `entity_ids`, `event_ids`, or typed event references and stores app pages and deep links for each selected event.

Create, update, and move operations accept `conflict_policy`:

- `allow` stores the event and reports any conflicts.
- `reject` returns a structured `calendar_conflict` error with compact conflicting events.
- `warn` stores the event and returns a warning payload containing the conflicts.

`calendar_move_event` can either accept `startTime` for a fixed reschedule or `move_strategy: "first_free"` with `start_after` and `end_before` to move the event to the first available slot in that window. First-free moves preserve the event duration, ignore the event being moved, and use the event's attendees when no attendee filter is provided.

## SDK Flow

`calendar` is an installation-level built-in app under `apps/calendar`, not a workspace-local app project. Validate this source tree with an explicit app root:

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id calendar --app-root apps/calendar --workspace default --json
```

`register-local`, `install-local`, and `package` operate on workspace-local app projects under `workspaces/<workspace_id>/apps/<app_id>/`; they are not the correct lifecycle for this built-in Calendar app source.

## Verification

```bash
cd apps/calendar
npm install
npm run build
cd ../..
./scripts/maverick core cli run core.app-sdk.validate --app-id calendar --app-root apps/calendar --workspace default --json
python3 -m unittest apps.calendar.tests.test_calendar_app
python3 -m unittest tests.contracts.app_contract.test_repository_contracts
maverick app <calendar_app_id> cli list --json
maverick app <calendar_app_id> mcp list --json
maverick app <calendar_app_id> frontend build --json
```


## Calendar reliability and everyday workflows

Remote fetching, event mapping, reconciliation and cursor persistence have separate
app-owned modules. Sync reconciles with the latest state under the SDK state lock.
Concurrent revisions and deletions are preserved and reported, and independent
accounts retain each other's events and cursors. Partial pagination has `synced:
false`, `status: partial` and a persisted continuation token. Repeating the sync
continues the identical query; absence-based deletion happens only after the final
page, using the revisions tracked across the whole pagination run. Errors do not
advance completion timestamps. Discovered calendars and local settings survive
incomplete calendar discovery. The account tree reports completion time, coverage,
partial results and errors; a visible online app refreshes stale provider data
(after fifteen minutes), coalesces requests and backs off after failures.

All-day events retain civil `all_day_start`/`all_day_end` dates in the event's IANA
timezone. The end is exclusive. Google serialization and drag moves preserve
civil dates across positive/negative offsets and daylight-saving transitions.
`transparency` is `opaque` (busy) or `transparent` (free), including Google imports.

Local recurrence accepts iCalendar `rules` or `frequency`, `interval`, `count`
and `until`. The recurrence engine is python-dateutil (declared in pyproject.toml).
Bounded lists, offline read models and availability expand series in the requested
window. Unbounded lists expose series records. Occurrence ids are stable
`<series-id>@<UTC-original-start>`; records include `series_id` and
`original_start_time`. Local edits use revision-guarded exceptions.
`recurrence_scope` accepts `occurrence`, `future` or `series`. Future edits split
the series and preserve the remaining repetition count. Google full-history
masters use the same expansion, with provider exceptions overriding generated
occurrences; Google series edits address the provider master and future edits
trim the old series before inserting its successor.

Google calendar transfers use `events.move`, require verified destination write
permissions and stay within one connected account. The accepted destination is
mirrored before applying accompanying edits, so a later edit failure leaves the
transfer visible. Other accounts and local destinations are excluded from the
transfer selector. UI creates carry a stable idempotency key; Google inserts
also derive a provider event id from it so retries after a lost response cannot
create another event.

Day/week views draw one block per timed event, with minute positions and columns
for overlaps. All-day rows are separate. Month moves keep the original time,
time-grid drops use fifteen-minute slots, month navigation clamps the selected
day and overflow opens the full day. Day/slot clicks create events at that time.
Global paginated search queries the local mirror across months; optional date
bounds also expand recurring series. Results navigate to the event.

The event panel includes location, attendees, timezone, status, busy/free, all-day,
recurrence, reminders and advanced metadata. Dirty drafts survive refresh, revision
errors retain the draft and offer explicit reload or retry, and dismissal checks
unsaved changes. Focus stays in the dialog and returns to the invoking control.
Events support Enter/Space and fields have labels. Mobile defaults to agenda and
has a visible create action. Language (Italian/English), first weekday and time
format are browser preferences. Working hours, weekdays and buffers are applied
by the shared free-slot planner for UI, CLI/MCP and first-free moves. Participant
results explicitly cover known local events, not all invitee calendars.

UI deletion has an eight-second undo window before any local or provider delete
is committed. Closing the app cancels an uncommitted deletion. Local popup
reminders appear in the open Calendar app; Google remains responsible for its
own reminders. Background delivery with a closed app is not claimed.


Regression verification covers concurrent accounts and edits, page continuation,
all-day roundtrips and DST, recurring exceptions and series transfers, workday
windows and buffers, month/time-grid interactions, keyboard event opening, draft
preservation and undo. Provider checks use temporary state and simulated responses;
no real appointments are changed by the test suite. Browser Lab verification of
`http://hostmachine:8014/app/calendar` reaches the sign-in page in its isolated
session, so authenticated desktop/mobile visual acceptance remains unverified.

Google future-series creation uses a deterministic successor id. A lost insert
response is resolved by reading that id; a confirmed failed insert restores the
original series. Uncertain results report the completed step and direct the user
to sync and review before retrying.

A temporary 5,000-event fixture measured account-summary reads at about 237 ms
(after removing repeated state reads and OAuth cleanup writes), versus 1,311 ms
before that cleanup. A 500-event display page took about 528 ms. These are local
single-run measurements, not production latency guarantees; JSON storage remains
in place while the sidebar avoids returning thousands of event records.

Visibility affects displayed lists. Explicit event ids still resolve hidden sources,
and Google writes retain provider routing and write-permission checks. Mutation
warnings use the same availability flags and recurrence expansion as planning.

A draft edited during event-detail loading merges only its changed fields over the
complete record. Saving waits for complete metadata, protecting provider recurrence
and reminders. Contextual creation also follows the visible day from the shell
sidebar action. UI behavior is verified with component tests and the official
frontend build, including the committed distribution assets.
