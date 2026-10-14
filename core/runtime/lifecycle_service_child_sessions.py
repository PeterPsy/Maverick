"""Create explicitly authorized child runtime sessions."""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from core.runtime.lifecycle_service_sessions import _optional_text, _skill_id_list, _platform_runtime_grants, utcnow
from core.runtime.execution_binding import copy_runtime_execution_binding_for_child
from core.runtime.paths import normalize_runtime_session_id
from core.runtime.session_preparation import prepare_runtime_session
from core.runtime.runtime_session import RuntimeSessionGrantRecord, RuntimeSessionRecord, SkillActivationMode, coerce_skill_activation_mode
from core.runtime.remote_agentic_admission import require_remote_agentic_session_admission
from core.runtime.store import RuntimeStore

def create_child_runtime_session(
    store: RuntimeStore,
    *,
    parent_session_id: str,
    child_session_id: str,
    child_agent_id: str,
    system_prompt: str | None = None,
    skill_ids: list[str] | None = None,
    skill_catalog_app_id: str | None = None,
    skill_activation_mode: SkillActivationMode | str | None = None,
    source_app_id: str | None = None,
    owner_user_id: str | None = None,
    created_by_user_id: str | None = None,
    grants: list[RuntimeSessionGrantRecord] | None = None,
    now: datetime | None = None,
    workspace_store: object | None = None,
) -> RuntimeSessionRecord:
    """Create one runtime child session using only explicit materialized authority."""
    parent = store.get_session(parent_session_id)
    require_remote_agentic_session_admission(
        parent.execution_binding,
        workspace_id=parent.workspace_id,
        workspace_store=workspace_store,
    )
    if parent.runtime_mode == "plain_hosted_chat":
        raise ValueError("Text-only runtime sessions cannot create agent children.")
    if parent.runtime_profile == "research":
        raise ValueError("Research runtime sessions cannot create agent children.")
    timestamp = now or utcnow()
    child_session_id = normalize_runtime_session_id(child_session_id)
    runtime_root = Path(parent.runtime_root).parent / child_session_id
    runtime_root.mkdir(parents=True, exist_ok=True)
    execution_binding = (
        copy_runtime_execution_binding_for_child(
            parent.execution_binding,
            session_id=child_session_id,
            created_at=timestamp,
        )
        if parent.execution_binding is not None
        else None
    )
    session = RuntimeSessionRecord(
        session_id=child_session_id,
        workspace_id=parent.workspace_id,
        agent_id=child_agent_id,
        status="created",
        requested_mode=parent.requested_mode,
        effective_mode=parent.effective_mode,
        workspace_root=parent.workspace_root,
        workdir=parent.workdir,
        runtime_root=str(runtime_root),
        started_at=None,
        updated_at=timestamp,
        ended_at=None,
        last_progress_at=None,
        preparation_status="unprepared",
        session_kind="inter_agent_participant",
        thread_visibility="hidden",
        runtime_mode=parent.runtime_mode,
        runtime_profile=parent.runtime_profile,
        system_prompt=_optional_text(system_prompt),
        skill_ids=_skill_id_list(skill_ids),
        skill_catalog_app_id=_optional_text(skill_catalog_app_id),
        skill_activation_mode=coerce_skill_activation_mode(skill_activation_mode),
        source_app_id=_optional_text(source_app_id),
        owner_user_id=_optional_text(owner_user_id),
        created_by_user_id=_optional_text(created_by_user_id),
        creator_runtime_session_id=parent.session_id,
        grants=_platform_runtime_grants(grants),
        execution_binding=execution_binding,
        provider_id=execution_binding.runtime_engine_id if execution_binding is not None else parent.provider_id,
        hosted_provider_id=parent.hosted_provider_id,
        hosted_model_id=parent.hosted_model_id,
    )
    saved, _published = prepare_runtime_session(store, session, execution_binding, now=timestamp)
    return saved
