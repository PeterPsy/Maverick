"""Durable session, provider-state, and thread writes for continuation forks."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from core.runtime.continuation_handoff import RuntimeContinuationHandoff
from core.runtime.errors import (
    RuntimeProviderStateError,
    RuntimeSessionNotFoundError,
    RuntimeThreadNotFoundError,
)
from core.runtime.execution_binding import canonical_digest
from core.providers.hosted_text_profiles import fork_hosted_text_execution_binding
from core.runtime.lifecycle import create_runtime_session, transition_runtime_session
from core.runtime.process_control import runtime_processes_alive_for_session
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.runtime_session import RuntimeSessionGrantRecord, RuntimeSessionRecord
from core.runtime.runtime_threads import create_runtime_thread


def ensure_successor_session(
    state,
    predecessor: RuntimeSessionRecord,
    handoff: RuntimeContinuationHandoff,
) -> RuntimeSessionRecord:
    """Create the exact child aggregate once and reject identity drift."""
    try:
        successor = state.runtime_store.get_session(handoff.successor_session_id)
    except RuntimeSessionNotFoundError:
        successor = create_runtime_session(
            state.runtime_store,
            session_id=handoff.successor_session_id,
            workspace_id=predecessor.workspace_id,
            agent_id=predecessor.agent_id,
            requested_mode=predecessor.requested_mode,
            system_prompt=predecessor.system_prompt,
            skill_ids=list(predecessor.skill_ids),
            skill_catalog_app_id=predecessor.skill_catalog_app_id,
            skill_activation_mode=predecessor.skill_activation_mode,
            source_app_id=predecessor.source_app_id,
            thread_title=predecessor.thread_title,
            agent_label=predecessor.agent_label,
            agent_type_id=predecessor.agent_type_id,
            agent_role_id=predecessor.agent_role_id,
            project_id=predecessor.project_id,
            owner_user_id=predecessor.owner_user_id,
            created_by_user_id=predecessor.created_by_user_id,
            creator_runtime_session_id=predecessor.creator_runtime_session_id,
            predecessor_session_id=predecessor.session_id,
            lineage_root_session_id=(
                predecessor.lineage_root_session_id or predecessor.session_id
            ),
            continuation_handoff_id=handoff.handoff_id,
            continuation_fork_reason=handoff.reason_code,
            session_kind=predecessor.session_kind,
            thread_visibility=predecessor.thread_visibility,
            runtime_mode=predecessor.runtime_mode,
            hosted_provider_id=predecessor.hosted_provider_id,
            hosted_model_id=predecessor.hosted_model_id,
            hosted_text_binding=(
                fork_hosted_text_execution_binding(
                    predecessor.hosted_text_binding,
                    session_id=handoff.successor_session_id,
                    created_at=handoff.created_at,
                )
                if getattr(predecessor, "hosted_text_binding", None) is not None
                else None
            ),
            declared_remote_data_class=None,
            grants=_session_grants(predecessor),
            governance=(
                None
                if getattr(state, "workspace_store", None) is None
                else state.workspace_store.get_governance(predecessor.workspace_id)
            ),
            platform_allows_full_access=predecessor.workspace_id == "default",
            now=handoff.created_at,
            start_path=getattr(state, "repository_root", None),
            observability_store=getattr(state, "observability_store", None),
            execution_binding=handoff.target_execution_binding,
            workspace_store=getattr(state, "workspace_store", None),
        )
    if (
        successor.predecessor_session_id != predecessor.session_id
        or successor.continuation_handoff_id != handoff.handoff_id
        or successor.execution_binding != handoff.target_execution_binding
        or not _same_hosted_text_route(predecessor, successor)
    ):
        raise RuntimeProviderStateError("runtime_continuation_successor_conflict")
    return successor


def _same_hosted_text_route(
    predecessor: RuntimeSessionRecord,
    successor: RuntimeSessionRecord,
) -> bool:
    source = getattr(predecessor, "hosted_text_binding", None)
    target = getattr(successor, "hosted_text_binding", None)
    if source is None or target is None:
        return source is target
    return (
        target.session_id == successor.session_id
        and target.workspace_id == source.workspace_id
        and target.profile == source.profile
        and target.status == source.status
        and target.certificate == source.certificate
        and target.provider_routing_digest == source.provider_routing_digest
        and target.provider_routing_snapshot == source.provider_routing_snapshot
    )


def transfer_provider_state(
    state,
    handoff: RuntimeContinuationHandoff,
) -> RuntimeProviderState:
    """Fence the source revision before copying continuation identifiers."""
    source = state.runtime_store.get_provider_state(handoff.predecessor_session_id)
    if source.continuation_handoff_id is None:
        if (
            source.revision != handoff.source_provider_state_revision
            or canonical_digest(source) != handoff.source_provider_state_digest
        ):
            raise RuntimeProviderStateError("runtime_continuation_provider_state_changed")
        source = state.runtime_store.fence_provider_state_for_continuation(
            session_id=source.session_id,
            expected_revision=handoff.source_provider_state_revision,
            handoff_id=handoff.handoff_id,
            successor_session_id=handoff.successor_session_id,
            now=handoff.updated_at,
        )
    elif (
        source.continuation_handoff_id != handoff.handoff_id
        or source.continuation_successor_session_id != handoff.successor_session_id
    ):
        raise RuntimeProviderStateError(
            "runtime_continuation_provider_state_fence_conflict"
        )
    target = state.runtime_store.get_provider_state(handoff.successor_session_id)
    desired = replace(
        target,
        continuation_id=source.continuation_id,
        provider_thread_id=source.provider_thread_id,
        provider_request_id=None,
        provider_private_envelope=None,
        turn_generation=None,
    )
    if desired == target:
        return target
    if target.revision != 0:
        raise RuntimeProviderStateError("runtime_continuation_provider_state_conflict")
    desired = replace(desired, revision=1, updated_at=handoff.updated_at)
    return state.runtime_store.update_provider_state(desired, expected_revision=0)


def close_predecessor_runtime_process(
    state,
    handoff: RuntimeContinuationHandoff,
) -> None:
    """Close the idle physical runtime before continuation state changes owner."""
    from core.recovery.continuation_admission import (
        runtime_session_has_nonterminal_turns,
    )
    from core.runtime.runtime_process_lifecycle import release_idle_runtime_processes

    predecessor = state.runtime_store.get_session(handoff.predecessor_session_id)
    if runtime_session_has_nonterminal_turns(state.runtime_store, predecessor.session_id):
        raise RuntimeProviderStateError("runtime_profile_upgrade_turn_busy")
    binding = predecessor.execution_binding
    release_idle_runtime_processes(
        state,
        session_id=predecessor.session_id,
        provider_id="unconfigured" if binding is None else binding.runtime_engine_id,
        reason="continuation_fork_predecessor_fenced",
        idle_ttl_seconds=0,
    )
    if runtime_processes_alive_for_session(predecessor.session_id):
        raise RuntimeProviderStateError(
            "runtime_continuation_predecessor_process_still_running"
        )


def quarantine_continuation_successor(
    state,
    handoff: RuntimeContinuationHandoff,
) -> None:
    """Stop an untrusted successor after live handoff revalidation fails."""
    from core.runtime.runtime_process_lifecycle import release_idle_runtime_processes
    from core.runtime.session_termination import terminate_runtime_session

    try:
        successor = state.runtime_store.get_session(handoff.successor_session_id)
    except RuntimeSessionNotFoundError:
        return
    terminate_runtime_session(
        state.runtime_store,
        session_id=successor.session_id,
        reason="continuation target authority invalid",
        event_bus=getattr(state, "runtime_event_bus", None),
        observability_store=getattr(state, "observability_store", None),
        start_path=getattr(state, "repository_root", None),
        provider_store=getattr(state, "provider_store", None),
        provider_registry=getattr(state, "provider_registry", None),
    )
    binding = successor.execution_binding
    release_idle_runtime_processes(
        state,
        session_id=successor.session_id,
        provider_id="unconfigured" if binding is None else binding.runtime_engine_id,
        reason="continuation_target_authority_invalid",
        idle_ttl_seconds=0,
    )
    if runtime_processes_alive_for_session(successor.session_id):
        raise RuntimeProviderStateError(
            "runtime_continuation_successor_process_still_running"
        )


def fence_predecessor_and_start_successor(
    state,
    handoff: RuntimeContinuationHandoff,
    *,
    start_successor: bool = True,
    now: datetime,
) -> None:
    """Make the closed predecessor non-executable and start its child."""
    predecessor = state.runtime_store.get_session(handoff.predecessor_session_id)
    if runtime_processes_alive_for_session(predecessor.session_id):
        raise RuntimeProviderStateError(
            "runtime_continuation_predecessor_process_still_running"
        )
    if predecessor.status in {"created", "running", "stopping"}:
        transition_runtime_session(
            state.runtime_store,
            session_id=predecessor.session_id,
            target_status="stopped",
            forced_stop_reason="continuation fork completed",
            observability_store=getattr(state, "observability_store", None),
            start_path=getattr(state, "repository_root", None),
            now=now,
        )
    successor = state.runtime_store.get_session(handoff.successor_session_id)
    target_status = "running" if start_successor else "stopped"
    if successor.status != target_status:
        transition_runtime_session(
            state.runtime_store,
            session_id=successor.session_id,
            target_status=target_status,
            forced_stop_reason=(
                None
                if start_successor
                else "continuation target requires another compatible upgrade"
            ),
            observability_store=getattr(state, "observability_store", None),
            start_path=getattr(state, "repository_root", None),
            now=now,
        )


def rebind_logical_thread(
    state,
    predecessor: RuntimeSessionRecord,
    successor: RuntimeSessionRecord,
    *,
    now: datetime,
):
    """CAS-move the stable chat-thread identity to the executable child."""
    thread = state.runtime_store.get_thread_by_runtime_session_id(
        workspace_id=predecessor.workspace_id,
        runtime_session_id=predecessor.session_id,
    )
    if thread is None:
        thread = state.runtime_store.get_thread_by_runtime_session_id(
            workspace_id=successor.workspace_id,
            runtime_session_id=successor.session_id,
        )
    if thread is None:
        try:
            thread = state.runtime_store.get_thread(predecessor.session_id)
        except RuntimeThreadNotFoundError:
            return create_runtime_thread(
                state.runtime_store,
                workspace_id=successor.workspace_id,
                thread_id=predecessor.session_id,
                runtime_session_id=successor.session_id,
                title=predecessor.thread_title or "New chat",
                agent_label=predecessor.agent_label or predecessor.agent_id,
                agent_type_id=predecessor.agent_type_id,
                agent_role_id=predecessor.agent_role_id,
                source_app_id=predecessor.source_app_id or predecessor.agent_id,
                system_prompt=predecessor.system_prompt or "",
                project_id=predecessor.project_id,
                now=predecessor.started_at or predecessor.updated_at,
            )
    return state.runtime_store.rebind_runtime_thread_session(
        workspace_id=thread.workspace_id,
        thread_id=thread.thread_id,
        predecessor_session_id=predecessor.session_id,
        successor_session_id=successor.session_id,
        now=now,
    )


def _session_grants(
    session: RuntimeSessionRecord,
) -> list[RuntimeSessionGrantRecord]:
    grants: list[RuntimeSessionGrantRecord] = []
    for value in session.grants:
        if isinstance(value, RuntimeSessionGrantRecord):
            grants.append(value)
        elif isinstance(value, dict):
            grants.append(RuntimeSessionGrantRecord(**value))
    return grants
