"""Result-policy and store support for executable shell/process evidence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.runtime.hosted_agentic_tool_results import pairing_safe_tool_result
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_admission_resolver,
    build_hosted_tool_result_preflight_resolver,
)
from core.runtime.public_content_authority import (
    build_runtime_public_content_authority_record,
)
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolSurfaceResult
from core.shared.in_memory_collection import InMemoryCollection


def shell_process_result_policy(
    registry,
    *,
    workspace_id: str,
    now: datetime,
):
    """Compose the production preflight/admission path for probe results."""
    public_authority = build_runtime_public_content_authority_record(
        workspace_id=workspace_id,
        actor_id="core-shell-process-probe",
        active=True,
        now=now,
    )
    authority_resolver = lambda candidate: (
        public_authority if candidate == workspace_id else None
    )
    admission = build_hosted_tool_result_admission_resolver(
        cli_registry=None,
        mcp_registry=None,
        public_content_authority_resolver=authority_resolver,
    )
    preflight = build_hosted_tool_result_preflight_resolver(
        cli_registry=None,
        mcp_registry=None,
        process_registry=registry,
        public_content_authority_resolver=authority_resolver,
    )
    return admission, preflight


def invoke_behavior_capability(
    capabilities,
    handle: str,
    arguments: dict[str, object],
    context: RuntimeToolActorContext,
    *,
    admission,
    preflight,
) -> RuntimeToolSurfaceResult:
    """Require production preflight and admission around one real handler."""
    decision = preflight(handle, arguments, context)
    if decision is None or not decision.admitted_before_effect:
        raise RuntimeError("hosted_result_preflight_denied")
    result = capabilities[handle].handler(arguments, context, None)
    if isinstance(result, RuntimeToolSurfaceResult):
        return result
    admitted = admission(handle, arguments, result, context)
    if not isinstance(admitted, RuntimeToolSurfaceResult):
        raise RuntimeError("hosted_result_admission_failed")
    return admitted


def public_and_pairable(result) -> bool:
    """Require the admitted result to survive public provider pairing."""
    if not isinstance(result, RuntimeToolSurfaceResult):
        return False
    paired = pairing_safe_tool_result(
        result.payload,
        is_error=False,
        result_data_class=result.classification.data_class,
        allowed_remote_data_classes=("public",),
    )
    return result.classification.data_class == "public" and paired == (
        result.payload,
        False,
    )


def behavior_payload(result) -> dict[str, object]:
    return result.payload if isinstance(result, RuntimeToolSurfaceResult) else {}


def build_behavior_runtime_store(
    workspace_root: Path,
    runtime_root: Path,
    *,
    workspace_id: str,
    session_id: str,
    now: datetime,
) -> RuntimeDocumentStore:
    """Build the session-owned in-memory process registry store."""
    collection = InMemoryCollection
    store = RuntimeDocumentStore(
        RuntimeCollections(
            sessions=collection(),
            turns=collection(),
            events=collection(),
            processes=collection(),
            states=collection(),
            threads=collection(),
            tool_invocations=collection(),
            tool_confirmation_grants=collection(),
        )
    )
    store.insert_session(
        RuntimeSessionRecord(
            session_id=session_id,
            workspace_id=workspace_id,
            agent_id="core-shell-process-probe",
            status="running",
            requested_mode="full-access",
            effective_mode="full-access",
            workspace_root=str(workspace_root),
            workdir=str(workspace_root),
            runtime_root=str(runtime_root),
            started_at=now,
            updated_at=now,
            ended_at=None,
            last_progress_at=now,
            source_app_id="chat",
            owner_user_id="core-shell-process-probe",
        )
    )
    return store


__all__ = [
    "behavior_payload",
    "build_behavior_runtime_store",
    "invoke_behavior_capability",
    "public_and_pairable",
    "shell_process_result_policy",
]
