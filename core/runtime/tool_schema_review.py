"""Direct trust marker for Core-owned tool schemas exposed to hosted models."""

from __future__ import annotations


REVIEWED_TOOL_SCHEMA_COMPONENT = "tool-schema-catalog"


def is_reviewed_tool_schema_component(component_id: str) -> bool:
    """Return whether the schema belongs to the reviewed Core tool catalog."""
    return component_id == REVIEWED_TOOL_SCHEMA_COMPONENT


__all__ = ["REVIEWED_TOOL_SCHEMA_COMPONENT", "is_reviewed_tool_schema_component"]
