"""Canonical in-memory tool results awaiting request-time egress approval."""

from __future__ import annotations

import json

from core.egress.classification import content_sha256
from core.providers.agentic_protocol import AgenticSourceMetadata, AgenticToolResult
from core.runtime.tool_models import ToolInvocationRecord


def pairing_safe_tool_result(
    result: dict[str, object],
    *,
    is_error: bool,
    result_data_class: str | None,
    allowed_remote_data_classes: tuple[str, ...],
) -> tuple[dict[str, object], bool]:
    """Replace a denied private result with a pairable public Core error."""
    if (
        not is_error
        and result_data_class not in allowed_remote_data_classes
    ):
        return {"error": "tool_result_egress_denied"}, True
    return result, is_error


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
            # Request-time artifact projection changes the provider-visible
            # bytes.  Bind semantic metadata to those exact bytes while the
            # remaining fields preserve the original result taint/evidence.
            source_block_digest=content_sha256(content),
            source_data_class=invocation.result_data_class,  # type: ignore[arg-type]
            source_trust_level=invocation.result_trust_level,
            provenance=invocation.result_provenance,
            source_ref=invocation.result_source_ref,
            source_revision=invocation.result_source_revision,
            resource_identity=invocation.result_resource_identity,
            classification_revision=invocation.result_classification_revision,
            classification_authority_id=(
                getattr(invocation, "result_classification_authority_id", "")
            ),
            classification_authority_kind=(
                getattr(invocation, "result_classification_authority_kind", "")
            ),
            classification_authority_ref=(
                getattr(invocation, "result_classification_authority_ref", "")
            ),
            classification_authority_revision=(
                getattr(
                    invocation,
                    "result_classification_authority_revision",
                    None,
                )
            ),
            classification_authority_digest=(
                getattr(invocation, "result_classification_authority_digest", "")
            ),
            classification_authority_policy_revision=(
                getattr(
                    invocation,
                    "result_classification_authority_policy_revision",
                    "",
                )
            ),
            classification_authority_bound=(
                getattr(
                    invocation,
                    "result_classification_authority_bound",
                    None,
                )
            ),
        )
    return AgenticToolResult(
        provider_tool_call_id=provider_tool_call_id,
        provider_tool_name=provider_tool_name,
        content_type="application/json",
        content=content,
        is_error=is_error,
        source_metadata=source_metadata,
    )


__all__ = ["make_agentic_tool_result", "pairing_safe_tool_result"]
