"""Durable artifact references and bounded projections for large tool results."""

from __future__ import annotations

import base64
import hashlib
import json

from core.egress.classification import CanonicalSourceClassification
from core.providers.agentic_models import AgenticContextPolicy
from core.runtime.tool_catalog import RuntimeToolSurfaceResult
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_full_workspace_support import (
    full_workspace_surface,
    require_workspace_context,
)
from core.runtime.tool_result_classification import (
    RuntimeToolClassificationProjection,
)


TOOL_RESULT_ARTIFACT_PREFIX = "runtime-tool-result:"
TOOL_RESULT_ARTIFACT_READ_HANDLE = "core-capability:artifact.read"
MAX_ARTIFACT_READ_BYTES = 65_536
MAX_ARTIFACT_READ_PROVIDER_RESULT_BYTES = 96 * 1_024
MIN_TOOL_RESULT_SUMMARY_BYTES = 1_024
MAX_PROJECTED_FIELD_NAMES = 64
MAX_PROJECTED_FIELD_NAME_BYTES = 128


def project_hosted_tool_result(
    result: dict[str, object],
    *,
    invocation,
    context_policy: AgenticContextPolicy | None,
) -> dict[str, object]:
    """Return inline data or an artifact reference with a bounded summary."""
    if context_policy is None or invocation.result_id is None:
        return result
    encoded = _encoded(result)
    if invocation.resolved_tool_handle == TOOL_RESULT_ARTIFACT_READ_HANDLE:
        # artifact.read is already the model's explicit bounded byte window.
        # Re-artifacting that response would create an unreadable reference
        # chain, so admit the verified chunk directly under its own hard cap.
        if len(encoded) > MAX_ARTIFACT_READ_PROVIDER_RESULT_BYTES:
            raise RuntimeToolError("tool_result_artifact_chunk_invalid")
        return result
    has_original_artifact = invocation.result_artifact_private_ref is not None
    if (
        len(encoded) <= context_policy.tool_result_inline_bytes
        and not has_original_artifact
    ):
        return result
    original_bytes = (
        invocation.result_artifact_size_bytes
        if has_original_artifact
        else len(encoded)
    )
    original_digest = (
        invocation.result_artifact_sha256
        if has_original_artifact
        else hashlib.sha256(encoded).hexdigest()
    )
    summary_limit = context_policy.tool_result_summary_bytes
    if (
        not isinstance(summary_limit, int)
        or isinstance(summary_limit, bool)
        or summary_limit < MIN_TOOL_RESULT_SUMMARY_BYTES
    ):
        raise RuntimeToolError("tool_result_summary_limit_invalid")
    field_names = tuple(sorted(str(key) for key in result))
    projected_names: list[str] = []
    summary: dict[str, object] = {
        "root_type": "object",
        "field_count": len(result),
        "projected_bytes": len(encoded),
        "field_names_digest": _field_names_digest(field_names),
        "field_names": projected_names,
        "omitted_field_names": len(field_names),
    }
    projection = {
        "artifact_ref": TOOL_RESULT_ARTIFACT_PREFIX + invocation.result_id,
        "artifact_content_type": "application/json",
        "artifact_encoding": "base64-chunks",
        "artifact_bytes": original_bytes,
        "artifact_sha256": original_digest,
        "summary": summary,
        "notice": (
            "The complete result is retained by Core. Use artifact.read with "
            "the artifact_ref and byte offsets when more detail is required."
        ),
    }
    if len(_encoded(projection)) > summary_limit:
        raise RuntimeToolError("tool_result_summary_limit_invalid")
    for field_name in field_names[:MAX_PROJECTED_FIELD_NAMES]:
        projected_names.append(_bounded_field_name(field_name))
        summary["omitted_field_names"] = len(field_names) - len(projected_names)
        if len(_encoded(projection)) > summary_limit:
            projected_names.pop()
            summary["omitted_field_names"] = len(field_names) - len(projected_names)
            break
    return projection


def build_tool_result_artifact_capabilities(
    *,
    ledger,
    workspace_id: str,
) -> tuple[object, ...]:
    """Expose session-owned byte-chunk reads over immutable result artifacts."""

    def read(arguments, context, _idempotency_key):
        require_workspace_context(context, workspace_id)
        artifact_ref = str(arguments.get("artifact_ref") or "").strip()
        if not artifact_ref.startswith(TOOL_RESULT_ARTIFACT_PREFIX):
            raise RuntimeToolError("tool_result_artifact_not_found")
        result_id = artifact_ref[len(TOOL_RESULT_ARTIFACT_PREFIX) :]
        if not result_id:
            raise RuntimeToolError("tool_result_artifact_not_found")
        invocation = next(
            (
                item
                for item in ledger.store.list_tool_invocations(
                    session_id=context.session_id
                )
                if item.result_id == result_id
                and item.workspace_id == context.workspace_id
                and item.session_id == context.session_id
            ),
            None,
        )
        if invocation is None or invocation.state != "succeeded":
            raise RuntimeToolError("tool_result_artifact_not_found")
        payload = ledger.load_result_artifact(invocation)
        offset = _integer(arguments.get("offset", 0), minimum=0)
        max_bytes = _integer(
            arguments.get("max_bytes", MAX_ARTIFACT_READ_BYTES),
            minimum=1,
            maximum=MAX_ARTIFACT_READ_BYTES,
        )
        if offset > len(payload):
            raise RuntimeToolError("tool_result_artifact_offset_invalid")
        chunk = payload[offset : offset + max_bytes]
        next_offset = offset + len(chunk)
        result = {
            "artifact_ref": artifact_ref,
            "content_type": "application/json",
            "encoding": "base64",
            "content": base64.b64encode(chunk).decode("ascii"),
            "offset": offset,
            "byte_count": len(chunk),
            "total_bytes": len(payload),
            "next_offset": next_offset,
            "has_more": next_offset < len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        return RuntimeToolSurfaceResult(
            result,
            _artifact_classification(invocation),
            RuntimeToolClassificationProjection.bind(
                result,
                omitted_paths=(("artifact_ref",), ("sha256",)),
            ),
        )

    schema = {
        "type": "object",
        "properties": {
            "artifact_ref": {"type": "string", "minLength": 1},
            "offset": {"type": "integer", "minimum": 0},
            "max_bytes": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_ARTIFACT_READ_BYTES,
            },
        },
        "required": ["artifact_ref"],
        "additionalProperties": False,
    }
    return (
        full_workspace_surface(
            TOOL_RESULT_ARTIFACT_READ_HANDLE.removeprefix("core-capability:"),
            "Read one immutable session-owned tool-result artifact by byte range.",
            schema,
            "read",
            read,
        ),
    )


def _artifact_classification(invocation) -> CanonicalSourceClassification:
    return CanonicalSourceClassification(
        data_class=invocation.result_data_class,
        provenance=invocation.result_provenance,
        trust_level=invocation.result_trust_level,
        source_ref=invocation.result_source_ref,
        source_revision=invocation.result_source_revision,
        source_digest=invocation.result_source_digest,
        resource_identity=invocation.result_resource_identity,
        classification_revision=invocation.result_classification_revision,
        classification_authority_id=(
            invocation.result_classification_authority_id
        ),
        classification_authority_kind=(
            invocation.result_classification_authority_kind
        ),
        classification_authority_ref=(
            invocation.result_classification_authority_ref
        ),
        classification_authority_revision=(
            invocation.result_classification_authority_revision
        ),
        classification_authority_digest=(
            invocation.result_classification_authority_digest
        ),
        classification_authority_policy_revision=(
            invocation.result_classification_authority_policy_revision
        ),
        classification_authority_bound=(
            invocation.result_classification_authority_bound
        ),
    )


def _encoded(value: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RuntimeToolError("tool_result_invalid") from error


def _bounded_field_name(value: str) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= MAX_PROJECTED_FIELD_NAME_BYTES:
        return value
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    prefix_limit = MAX_PROJECTED_FIELD_NAME_BYTES - len(f"…#{digest}".encode("utf-8"))
    prefix = encoded[:prefix_limit].decode("utf-8", errors="ignore")
    return f"{prefix}…#{digest}"


def _field_names_digest(values: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for value in values:
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _integer(value: object, *, minimum: int, maximum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise RuntimeToolError("tool_arguments_invalid")
    if maximum is not None and value > maximum:
        raise RuntimeToolError("tool_arguments_invalid")
    return value


__all__ = [
    "MAX_ARTIFACT_READ_BYTES",
    "MAX_ARTIFACT_READ_PROVIDER_RESULT_BYTES",
    "MIN_TOOL_RESULT_SUMMARY_BYTES",
    "TOOL_RESULT_ARTIFACT_PREFIX",
    "TOOL_RESULT_ARTIFACT_READ_HANDLE",
    "build_tool_result_artifact_capabilities",
    "project_hosted_tool_result",
]
