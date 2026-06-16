"""Calendar backend constants shared by domain modules."""

from __future__ import annotations

STATE_FILE = "state.json"
SCHEMA_VERSION = "3"
MUTATING_ACTIONS = {"create", "update", "delete", "move"}
VIEW_STATE_ACTIONS = {"set_view_filter", "set_custom_view", "clear_custom_view"}
MAX_EVENTS = 10_000
MAX_CONNECTIONS = 25
MAX_REMOTE_CALENDARS = 250
MAX_SYNC_CURSORS = 250
MAX_TITLE_LENGTH = 160
MAX_DESCRIPTION_LENGTH = 5000
MAX_CATEGORY_LENGTH = 80
MAX_LOCATION_LENGTH = 240
MAX_ORGANIZER_LENGTH = 160
MAX_SOURCE_LENGTH = 80
MAX_TIMEZONE_LENGTH = 80
MAX_PROVIDER_ID_LENGTH = 320
MAX_EXTERNAL_LINK_LENGTH = 2048
MAX_METADATA_LENGTH = 5000
MAX_LIST_ITEMS = 50
MAX_LIST_ITEM_LENGTH = 120
AGENT_DEFAULT_LIST_LIMIT = 50
ALLOWED_COLORS = {"blue", "green", "purple", "orange", "pink", "red"}
ALLOWED_CONFLICT_POLICIES = {"allow", "reject", "warn"}
ALLOWED_EVENT_STATUSES = {"confirmed", "tentative", "cancelled"}
ALLOWED_CONNECTION_STATUSES = {"pending", "connected", "disabled", "error"}
ALLOWED_SYNC_STATUSES = {"idle", "syncing", "ok", "error", "disabled"}
GOOGLE_PROVIDER = "google"
GOOGLE_REFRESH_TOKEN_LOGICAL_NAME = "google-calendar-refresh-token"
EVENT_FIELDS = {
    "title",
    "description",
    "startTime",
    "start_time",
    "endTime",
    "end_time",
    "color",
    "category",
    "attendees",
    "tags",
    "status",
    "timezone",
    "location",
    "organizer",
    "all_day",
    "allDay",
    "source",
    "external_refs",
    "externalRefs",
    "recurrence",
    "reminders",
    "idempotency_key",
    "idempotencyKey",
}
