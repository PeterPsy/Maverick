"""JSON schemas shared by core CLI and MCP transcript surfaces."""

from __future__ import annotations


THREAD_LIST_ARGUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "maxLength": 240},
        "source_app_id": {"type": "string", "maxLength": 120},
        "agent_type_id": {"type": "string", "maxLength": 160},
        "project_id": {"type": "string", "maxLength": 240},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        "cursor": {"type": "string", "maxLength": 240},
    },
    "additionalProperties": False,
}

TRANSCRIPT_READ_ARGUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "thread_id": {"type": "string", "minLength": 1, "maxLength": 240},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 30},
        "before_cursor": {"type": "string", "maxLength": 320},
        "snapshot_newest_event_id": {"type": "string", "maxLength": 320},
        "profile": {"type": "string", "enum": ["messages"], "default": "messages"},
    },
    "required": ["thread_id"],
    "additionalProperties": False,
}

TRANSCRIPT_MESSAGE_READ_ARGUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "thread_id": {"type": "string", "minLength": 1, "maxLength": 240},
        "message_id": {"type": "string", "minLength": 1, "maxLength": 320},
        "offset": {"type": "integer", "minimum": 0, "default": 0},
        "max_chars": {"type": "integer", "minimum": 1, "maximum": 12000, "default": 12000},
        "snapshot_newest_event_id": {"type": "string", "maxLength": 320},
    },
    "required": ["thread_id", "message_id"],
    "additionalProperties": False,
}
