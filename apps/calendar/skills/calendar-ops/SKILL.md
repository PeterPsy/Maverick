---
name: calendar-ops
description: Use the Calendar app to inspect, create, move, and summarize workspace events through official Maverick surfaces.
---

# Calendar Operations

Use this skill when the user asks about workspace calendar events, availability, schedule summaries, or event references.

Operate through Calendar's scoped MCP or CLI surfaces. Resolve the installed local app id first with `maverick apps list --json`; use `calendar` only when that is the workspace binding id.

- Discover MCP tools with `maverick app <calendar_app_id> mcp list --json`.
- Inspect MCP schemas with `maverick app <calendar_app_id> mcp inspect <tool_name> --json`.
- Invoke MCP tools with `maverick app <calendar_app_id> mcp call <tool_name> ...`.
- Discover CLI commands with `maverick app <calendar_app_id> cli list --json`.
- Invoke CLI commands with `maverick app <calendar_app_id> cli run calendar --json ...` or `maverick app <calendar_app_id> cli run calendar-reference --json ...`.

Do not read or write `data/calendar/state.json` directly. Calendar owns its storage and validates through its app surfaces.

Prefer these operations:

- `calendar_operations_manifest`: read the compact operation manifest before using an unfamiliar action.
- `calendar_list_events`: list events with bounded filters. Prefer `profile=compact` unless the user needs full descriptions.
- `calendar_check_availability`: answer whether a specific time window is free.
- `calendar_find_free_time`: find candidate slots before creating or moving events when availability matters.
- `calendar_create_event`: create one event after collecting title, start time, end time, and timezone context.
- `calendar_move_event`: reschedule an event while preserving duration unless the user gave a new end time. Use `move_strategy=first_free` with `start_after` and `end_before` when the user asks for the first available slot.
- `calendar_update_event`: update event details by id.
- `calendar_delete_event`: delete one event by id.
- `calendar_reference_search`, `calendar_reference_resolve`, and `calendar_reference_summarize`: handle mentions, deep links, and compact event context.
- `calendar_set_view_filter`, `calendar_set_custom_view`, `calendar_view_filter`, and `calendar_clear_custom_view`: prepare the Calendar UI for a requested time window, search filter, conflict-only view, or curated event set.

Always handle time explicitly. If the user gives a relative or local time, resolve it against the active workspace/user context and send ISO 8601 timestamps with an explicit offset or `Z`. Pass `timezone` when it is known so Calendar can preserve the user's scheduling context; if the timezone is ambiguous and the action would mutate the calendar, ask for clarification.

Use `conflict_policy` intentionally:

- Use `reject` when the user asked to avoid conflicts.
- Use `warn` when the user wants the event created or moved but should be told about overlaps.
- Use `allow` only when the user explicitly accepts conflicts or conflicts do not matter.

Calendar events can be `confirmed`, `tentative`, or `cancelled`. Treat confirmed and tentative events as busy; cancelled events remain visible history but do not block availability or free-time search.

Calendar normalizes event metadata for orchestration. Use `location`, `organizer`, `all_day`, `source`, `external_refs`, `recurrence`, `reminders`, and `idempotency_key` only when those values are genuinely known or needed; do not invent metadata.

When retrying a create after a transport or runtime interruption, reuse the same `idempotency_key` so Calendar can return the existing event instead of creating a duplicate. When updating, moving, or deleting an event you previously read, pass its current `revision` as `expected_revision`; if Calendar returns `revision_conflict`, resolve or present the returned `current_event` before retrying.

For destructive or high-impact changes, ask for confirmation before proceeding. This includes deletes, changes to multiple events, moving events with attendees, or creating/moving events that the availability tools report as conflicting.

When returning calendar references to the user, include the event title, time window, and deep link from the reference payload instead of exposing internal storage paths.

When the user asks to show a view, use Calendar's view surface instead of describing how to filter manually. Use `calendar_set_view_filter` with `query`, `start_after`, `end_before`, `category`, `attendee`, `tags`, or `conflicts_only`; use `preserve_custom=true` when refining an existing curated view. Use `calendar_set_custom_view` with resolved event references when the user asks to open or pin a specific set of events.
