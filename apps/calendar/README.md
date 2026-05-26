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

Widgets remain intentionally out of this phase.

## Surfaces

- Frontend: `frontend/dist`, mounted as the workspace app view.
- Backend: `backend/app_backend.py`, used by the frontend through `/api/apps/calendar/backend`.
- MCP: `mcp/server.py`, exposing scoped tools for event CRUD, moving events, availability checks, free-time search, and event references.
- CLI: `cli/app_cli.py`, exposing `calendar` and `calendar-reference` commands through the core-managed app CLI surface.
- Hooks: install, migrate, and health check create and validate `data/calendar/state.json`.
- References: Calendar declares `event` as a searchable, resolvable, summarizable reference entity. Reference payloads include `app_id`, `entity_type`, `entity_id`, `title`, `subtitle`, `summary`, `app_page`, `deep_link`, and `safe_fields`.
- View surface: Calendar declares the standard `calendar` view surface with `view_filter`, `set_view_filter`, `set_custom_view`, and `clear_custom_view` actions so references can open or curate event views through official surfaces. `set_view_filter` accepts `conflicts_only` for conflict-focused views and `preserve_custom` to refine a curated event set. The frontend reads that persisted state, listens for `view-state` data events, and shifts the active calendar viewport to the requested time window, conflict list, or curated event list.
- Skills: `skills/calendar-ops/SKILL.md` is declared through `capabilities.skills` and guides agents to use scoped Calendar MCP/CLI surfaces, avoid direct state-file access, resolve timezone ambiguity, and check availability before conflict-sensitive mutations.
- Widgets are still omitted from this product slice.

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

The `calendar` CLI command supports `list`, `create`, `update`, `delete`, `move`, `check_availability`, `find_free_time`, `view_filter`, `set_view_filter`, `set_custom_view`, and `clear_custom_view`. The `calendar-reference` CLI command supports `references.manifest`, `references.search`, `references.resolve`, and `references.summarize`.

## Storage

The app owns JSON state under:

```text
workspaces/<workspace_id>/data/calendar/state.json
```

The state file stores `schema_version` and an `events` array. The current data schema version is `2`. Event timestamps are serialized as ISO 8601 strings and converted to `Date` objects by the frontend.

Event ids are generated by the Calendar backend. Mutating requests validate required title and time fields, reject events whose end time is not after the start time, and bound free-form strings and list fields before writing to `state.json`.

Events include a `status` field with `confirmed`, `tentative`, or `cancelled`; omitted status defaults to `confirmed`. Availability, conflict checks, and free-time search ignore cancelled events.

Every event is normalized with orchestration fields for agent workflows. Omitted `timezone` defaults to `UTC`, `all_day` defaults to `false`, `source` defaults to `calendar`, `revision` defaults to `1`, and legacy records missing `created_at`/`updated_at` receive stable timestamp defaults from their `startTime`. Create operations generate `created_at`, `updated_at`, and `revision: 1`; update and move operations preserve `created_at` while incrementing `revision` and refreshing `updated_at`. `external_refs` and `recurrence` are bounded JSON objects, while `reminders` is a bounded JSON array.

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
