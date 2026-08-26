"""Schema and bounds for the canonical confined filesystem listing."""

from __future__ import annotations

MAX_FILESYSTEM_LIST_DEPTH = 4
MAX_FILESYSTEM_LIST_RESULTS = 500


def filesystem_list_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 4096},
            "max_depth": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_FILESYSTEM_LIST_DEPTH,
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_FILESYSTEM_LIST_RESULTS,
            },
            "cursor": {"type": "string", "minLength": 1, "maxLength": 8192},
        },
        "additionalProperties": False,
    }
