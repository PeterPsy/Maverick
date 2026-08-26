"""Canonical in-memory tool results awaiting request-time egress approval."""

from __future__ import annotations

import json

from core.egress.classification import content_sha256
from core.providers.agentic_protocol import AgenticSourceMetadata, AgenticToolResult
from core.runtime.tool_models import ToolInvocationRecord


def make_agentic_tool_result(
    *,
    provider_tool_call_id: str,
    provider_tool_name: str,
    result: dict[str, object],
    is_error: bool,
    invocation: ToolInvocationRecord | None = None,
) -> AgenticToolResult:
    content = json.dumps(
        result,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    source_metadata = None
    if is_error:
        reason_code = str(result.get("error") or "tool_failed")
        source_metadata = AgenticSourceMetadata(
            source_block_digest=content_sha256(content),
            source_data_class="public",
            source_trust_level="trusted_platform",
            provenance="tool_result",
            source_ref=f"core-tool-error:{reason_code}",
            source_revision="1",
            resource_identity=f"core-tool-error:{reason_code}:1",
            classification_revision=1,
        )
    elif invocation is not None:
        source_metadata = AgenticSourceMetadata(
            source_block_digest=invocation.result_source_digest,
            source_data_class=invocation.result_data_class,  # type: ignore[arg-type]
            source_trust_level=invocation.result_trust_level,
            provenance=invocation.result_provenance,
            source_ref=invocation.result_source_ref,
            source_revision=invocation.result_source_revision,
            resource_identity=invocation.result_resource_identity,
            classification_revision=invocation.result_classification_revision,
        )
    return AgenticToolResult(
        provider_tool_call_id=provider_tool_call_id,
        provider_tool_name=provider_tool_name,
        content_type="application/json",
        content=content,
        is_error=is_error,
        source_metadata=source_metadata,
    )
