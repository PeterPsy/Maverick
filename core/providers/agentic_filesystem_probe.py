"""Synthetic probe fixture backed by the real ``filesystem.list`` capability."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from core.providers.agentic_protocol import (
    AgenticToolCall,
    AgenticToolDefinition,
    AgenticToolResult,
)
from core.runtime.tool_catalog import RuntimeCoreCapabilityHandler, RuntimeToolActorContext
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_schema import provider_tool_name


FILESYSTEM_LIST_PROBE_HANDLE = "core-capability:filesystem.list"
FILESYSTEM_LIST_PROBE_TOOL_NAME = provider_tool_name(FILESYSTEM_LIST_PROBE_HANDLE)
FILESYSTEM_LIST_PROBE_MARKER = "certification-probe-marker.txt"


@dataclass(frozen=True)
class AgenticFilesystemListProbe:
    """Real provider alias, schema, and handler over an isolated synthetic root."""

    definition: AgenticToolDefinition
    handler: RuntimeCoreCapabilityHandler
    context: RuntimeToolActorContext

    @classmethod
    def create(cls, root: Path) -> "AgenticFilesystemListProbe":
        root.mkdir(parents=True, exist_ok=True)
        (root / FILESYSTEM_LIST_PROBE_MARKER).write_text(
            "synthetic certification marker",
            encoding="utf-8",
        )
        surface = next(
            item
            for item in build_core_runtime_tool_capabilities(
                workspace_id="certification-probe",
                workspace_root=root,
            )
            if item.definition.handle == FILESYSTEM_LIST_PROBE_HANDLE
        )
        return cls(
            definition=AgenticToolDefinition(
                name=FILESYSTEM_LIST_PROBE_TOOL_NAME,
                description=surface.definition.description,
                input_schema=surface.definition.input_schema,
            ),
            handler=surface.handler,
            context=RuntimeToolActorContext(
                workspace_id="certification-probe",
                actor_id="certification-probe",
                agent_id="certification-probe",
                platform_role=None,
                workspace_role="member",
                session_id="certification-probe",
                execution_mode="sandbox",
            ),
        )

    def execute(self, call: AgenticToolCall) -> AgenticToolResult:
        """Execute the exact real handler and require the isolated marker result."""
        if call.provider_tool_name != self.definition.name:
            raise ValueError("probe_tool_name_invalid")
        result = self.handler(call.arguments, self.context, None)
        entries = result.get("entries") if isinstance(result, dict) else None
        if not isinstance(entries, list) or not any(
            isinstance(item, dict)
            and item.get("path") == FILESYSTEM_LIST_PROBE_MARKER
            and item.get("type") == "file"
            for item in entries
        ):
            raise ValueError("probe_filesystem_marker_missing")
        encoded = json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return AgenticToolResult(
            provider_tool_call_id=call.provider_tool_call_id,
            provider_tool_name=call.provider_tool_name,
            content_type="application/json",
            content=encoded,
            is_error=False,
        )


__all__ = [
    "AgenticFilesystemListProbe",
    "FILESYSTEM_LIST_PROBE_HANDLE",
    "FILESYSTEM_LIST_PROBE_MARKER",
    "FILESYSTEM_LIST_PROBE_TOOL_NAME",
]
