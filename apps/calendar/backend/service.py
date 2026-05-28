"""Compatibility facade for Calendar backend operations."""

from __future__ import annotations

from actions import app_events_for_action, describe, handle_action, health_payload, mcp_result_for_tool
from availability import check_availability, find_free_time
from constants import AGENT_DEFAULT_LIST_LIMIT
from google_mutations import secret_lookup_for_remote_mutation
from google_calendars import list_calendars, select_calendar
from google_oauth import complete_oauth, disconnect_connection, list_connections, provider_status, start_oauth
from operations import create_event, delete_event, list_events, move_event, update_event
from references import reference_resolve, reference_search, reference_summarize
from store import default_state, normalize_state_for_storage
from view_state import clear_custom_view, read_view_filter, set_custom_view, set_view_filter


__all__ = [
    "AGENT_DEFAULT_LIST_LIMIT",
    "app_events_for_action",
    "check_availability",
    "clear_custom_view",
    "complete_oauth",
    "create_event",
    "default_state",
    "delete_event",
    "describe",
    "disconnect_connection",
    "find_free_time",
    "handle_action",
    "health_payload",
    "list_events",
    "list_connections",
    "list_calendars",
    "mcp_result_for_tool",
    "move_event",
    "normalize_state_for_storage",
    "provider_status",
    "read_view_filter",
    "reference_resolve",
    "reference_search",
    "reference_summarize",
    "set_custom_view",
    "set_view_filter",
    "select_calendar",
    "secret_lookup_for_remote_mutation",
    "start_oauth",
    "update_event",
]
