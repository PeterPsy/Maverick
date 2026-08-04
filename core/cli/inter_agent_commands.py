"""Inter-agent core CLI commands."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from core.api.runtime_cleanup import cleanup_runtime_session
from core.authorization.errors import AuthorizationError
from core.cli.core_command_helpers import WORKSPACE_SAFE, core_cli_command
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.identity.store import IdentityStore
from core.inter_agent.authorization import (
    authorize_inter_agent_participant_spawn,
    authorize_inter_agent_root_session_use,
    authorize_inter_agent_run_operation,
)
from core.inter_agent.executor import execute_inter_agent_run
from core.inter_agent.feature_flags import validate_product_inter_agent_run_mode
from core.inter_agent.orchestration_resume import OrchestrationResume, resume_run_from_surface
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import InterAgentStore
from core.inter_agent.surfaces import execution_result_payload, inter_agent_payload, run_detail_payload, run_spec_from_payload
from core.providers.store import ProviderStore
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.session_termination import terminate_runtime_session
from core.runtime.store import RuntimeStore
from core.workspaces.store import WorkspaceStore


def inter_agent_command_specs(
    *,
    app_store=None,
    identity_store: IdentityStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    inter_agent_store: InterAgentStore | None = None,
    secret_store=None,
    observability_store=None,
    runtime_event_bus=None,
    runtime_thread_event_bus=None,
    app_event_bus=None,
    orchestration_resume: OrchestrationResume | None = None,
    start_path=None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build core inter-agent command specs."""

    def _service() -> InterAgentService:
        if inter_agent_store is None:
            raise RuntimeError("inter_agent_store is required for inter-agent CLI commands.")
        return InterAgentService(inter_agent_store)

    def _state() -> SimpleNamespace:
        return SimpleNamespace(
            app_store=app_store,
            workspace_store=workspace_store,
            provider_store=provider_store,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            runtime_event_bus=runtime_event_bus,
            runtime_thread_event_bus=runtime_thread_event_bus,
            app_event_bus=app_event_bus,
            secret_store=secret_store,
            observability_store=observability_store,
            repository_root=start_path,
        )

    def _authorized_run(arguments: dict[str, Any], context: CliInvocationContext):
        if inter_agent_store is None:
            raise RuntimeError("inter_agent_store is required for inter-agent CLI commands.")
        workspace_id = _workspace_id(context, arguments)
        run = inter_agent_store.get_run(_text(arguments.get("run_id")), workspace_id=workspace_id)
        authorize_inter_agent_run_operation(
            workspace_store=workspace_store,
            context_workspace_id=workspace_id,
            caller_kind=context.caller_kind,
            run=run,
            user_id=context.user_id,
            platform_role=context.platform_role,
            workspace_role=context.workspace_role,
        )
        return run

    def _create(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if runtime_store is None:
            raise RuntimeError("runtime_store is required for inter-agent run creation.")
        workspace_id = _workspace_id(context, arguments)
        user_id = context.user_id or "operator"
        root_session = _root_session(runtime_store, workspace_id=workspace_id, arguments=arguments)
        authorize_inter_agent_root_session_use(
            workspace_store=workspace_store,
            identity_store=identity_store,
            context_workspace_id=workspace_id,
            caller_kind=context.caller_kind,
            root_session=root_session,
            user_id=context.user_id,
            platform_role=context.platform_role,
            workspace_role=context.workspace_role,
            caller_runtime_session_id=context.runtime_session_id,
        )
        spec = run_spec_from_payload(
            arguments,
            workspace_id=workspace_id,
            created_by_user_id=user_id,
            source_app_id=root_session.source_app_id or "chat",
        )
        validate_product_inter_agent_run_mode(spec.mode)
        run = _service().create_run(spec)
        return run_detail_payload(inter_agent_store, run)  # type: ignore[arg-type]

    def _spawn(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if runtime_store is None:
            raise RuntimeError("runtime_store is required for participant spawn.")
        workspace_id = _workspace_id(context, arguments)
        run = _authorized_run(arguments, context)
        owner_user_id = _text(arguments.get("owner_user_id")) or None
        authorize_inter_agent_participant_spawn(
            workspace_store=workspace_store,
            runtime_store=runtime_store,
            identity_store=identity_store,
            context_workspace_id=workspace_id,
            caller_kind=context.caller_kind,
            run=run,
            owner_user_id=owner_user_id,
            user_id=context.user_id,
            platform_role=context.platform_role,
            workspace_role=context.workspace_role,
        )
        root_session = _root_session_by_id(runtime_store, workspace_id=workspace_id, session_id=run.root_runtime_session_id)
        authorize_inter_agent_root_session_use(
            workspace_store=workspace_store,
            identity_store=identity_store,
            context_workspace_id=workspace_id,
            caller_kind=context.caller_kind,
            root_session=root_session,
            user_id=context.user_id,
            platform_role=context.platform_role,
            workspace_role=context.workspace_role,
            caller_runtime_session_id=context.runtime_session_id,
        )
        participant, session, created = _service().spawn_participant_runtime_session(
            runtime_store,
            workspace_id=workspace_id,
            run_id=run.run_id,
            participant_id=_text(arguments.get("participant_id")),
            child_session_id=_text(arguments.get("child_session_id")) or None,
            child_agent_id=_text(arguments.get("child_agent_id")) or None,
            owner_user_id=owner_user_id,
            created_by_user_id=context.user_id,
        )
        return {
            "created": created,
            "participant": inter_agent_payload(participant),
            "runtime_session": inter_agent_payload(session),
        }

    def _send(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if runtime_store is None:
            raise RuntimeError("runtime_store is required for message send.")
        run = _authorized_run(arguments, context)
        participant, turn, events = _service().send_runtime_message(
            _state(),
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            participant_id=_text(arguments.get("participant_id")),
            input_text=_text(arguments.get("input_text")) or _text(arguments.get("message")),
            client_message_id=_text(arguments.get("client_message_id")) or None,
            async_requested=bool(arguments.get("async")),
        )
        return {
            "participant": inter_agent_payload(participant),
            "turn": inter_agent_payload(turn),
            "events": inter_agent_payload(events),
        }

    def _execute(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if runtime_store is None:
            raise RuntimeError("runtime_store is required for inter-agent execution.")
        run = _authorized_run(arguments, context)
        validate_product_inter_agent_run_mode(run.mode)
        root_session = _root_session_by_id(runtime_store, workspace_id=run.workspace_id, session_id=run.root_runtime_session_id)
        authorize_inter_agent_root_session_use(
            workspace_store=workspace_store,
            identity_store=identity_store,
            context_workspace_id=run.workspace_id,
            caller_kind=context.caller_kind,
            root_session=root_session,
            user_id=context.user_id,
            platform_role=context.platform_role,
            workspace_role=context.workspace_role,
            caller_runtime_session_id=context.runtime_session_id,
        )
        if _run_has_child_runtime_participants(inter_agent_store, run):  # type: ignore[arg-type]
            authorize_inter_agent_participant_spawn(
                workspace_store=workspace_store,
                runtime_store=runtime_store,
                identity_store=identity_store,
                context_workspace_id=run.workspace_id,
                caller_kind=context.caller_kind,
                run=run,
                owner_user_id=None,
                user_id=context.user_id,
                platform_role=context.platform_role,
                workspace_role=context.workspace_role,
            )
        allow_synthetic = _allow_synthetic_execution(arguments, caller_kind=context.caller_kind)
        controlled_participants = arguments.get("controlled_participants") if isinstance(arguments.get("controlled_participants"), dict) else None
        if controlled_participants is not None and not allow_synthetic:
            raise AuthorizationError("inter_agent_controlled_participants_forbidden")
        result = execute_inter_agent_run(
            _service(),
            _state(),
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            input_text=_text(arguments.get("input_text")) or _text(arguments.get("message")),
            participant_inputs=arguments.get("participant_inputs") if isinstance(arguments.get("participant_inputs"), dict) else None,
            controlled_participants=controlled_participants,
            allow_synthetic_participants=allow_synthetic,
        )
        return execution_result_payload(inter_agent_store, result)  # type: ignore[arg-type]

    def _wait(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        run = _authorized_run(arguments, context)
        run = _service().wait_for_run(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            timeout_seconds=float(arguments.get("timeout_seconds") or 0),
        )
        return run_detail_payload(inter_agent_store, run)  # type: ignore[arg-type]

    def _interrupt(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        run = _authorized_run(arguments, context)
        result = _service().interrupt_run(
            _state(),
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            participant_id=_text(arguments.get("participant_id")) or None,
            reason=_text(arguments.get("reason")) or "inter_agent_interrupt",
        )
        return inter_agent_payload(result)

    def _resume(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        run = _authorized_run(arguments, context)
        run = resume_run_from_surface(
            _service(),
            _state(),
            run,
            reason=_text(arguments.get("reason")) or "inter_agent_resume",
            orchestration_resume=orchestration_resume,
        )
        return run_detail_payload(inter_agent_store, run)  # type: ignore[arg-type]

    def _close(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        state = _state()
        run = _authorized_run(arguments, context)
        result = _service().close_run(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            cleanup_runtime_session=lambda session_id, reason: _cleanup_runtime_session(
                state,
                session_id=session_id,
                reason=reason,
            ),
            reason=_text(arguments.get("reason")) or "inter_agent_run_closed",
            terminal_status=_text(arguments.get("terminal_status")) or "cancelled",
            delete_records=bool(arguments.get("delete_records")),
        )
        return inter_agent_payload(result)

    return [
        (
            core_cli_command(
                command_id="inter-agent.runs.create",
                path_segments=["inter-agent", "runs", "create"],
                description="Create one inter-agent run record for the active workspace.",
                owner_id="inter_agent",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _create,
        ),
        (
            core_cli_command(
                command_id="inter-agent.participants.spawn",
                path_segments=["inter-agent", "participants", "spawn"],
                description="Spawn one hidden runtime session for a child participant.",
                owner_id="inter_agent",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _spawn,
        ),
        (
            core_cli_command(
                command_id="inter-agent.messages.send",
                path_segments=["inter-agent", "messages", "send"],
                description="Send one runtime turn to a spawned child participant.",
                owner_id="inter_agent",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _send,
        ),
        (
            core_cli_command(
                command_id="inter-agent.runs.execute",
                path_segments=["inter-agent", "runs", "execute"],
                description="Execute one native MVP inter-agent run and project selected summaries to the root session.",
                owner_id="inter_agent",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _execute,
        ),
        (
            core_cli_command(
                command_id="inter-agent.runs.wait",
                path_segments=["inter-agent", "runs", "wait"],
                description="Wait briefly for an inter-agent run to reach a terminal state.",
                owner_id="inter_agent",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _wait,
        ),
        (
            core_cli_command(
                command_id="inter-agent.runs.interrupt",
                path_segments=["inter-agent", "runs", "interrupt"],
                description="Interrupt active child participant work for one run.",
                owner_id="inter_agent",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _interrupt,
        ),
        (
            core_cli_command(
                command_id="inter-agent.runs.resume",
                path_segments=["inter-agent", "runs", "resume"],
                description="Resume a paused run through the hosted scheduler handoff.",
                owner_id="inter_agent",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _resume,
        ),
        (
            core_cli_command(
                command_id="inter-agent.runs.close",
                path_segments=["inter-agent", "runs", "close"],
                description="Close one inter-agent run and clean up child runtime sessions.",
                owner_id="inter_agent",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _close,
        ),
    ]


def _cleanup_runtime_session(state: SimpleNamespace, *, session_id: str, reason: str) -> dict[str, object]:
    if _has_full_cleanup_state(state):
        return cleanup_runtime_session(
            state,
            session_id=session_id,
            reason=reason,
            start_path=state.repository_root,
            allow_hidden_inter_agent_cleanup=True,
        )
    if state.runtime_store is None:
        return {"session_id": session_id, "found": False}
    termination = terminate_runtime_session(
        state.runtime_store,
        session_id=session_id,
        reason=reason,
        event_bus=state.runtime_event_bus,
        observability_store=state.observability_store,
        start_path=state.repository_root,
    )
    return {**termination, "deleted": state.runtime_store.delete_session_records(session_id)}


def _has_full_cleanup_state(state: SimpleNamespace) -> bool:
    return all(
        getattr(state, attribute, None) is not None
        for attribute in (
            "app_store",
            "workspace_store",
            "inter_agent_store",
            "runtime_event_bus",
            "runtime_thread_event_bus",
            "app_event_bus",
            "secret_store",
        )
    )


def _workspace_id(context: CliInvocationContext, arguments: dict[str, Any]) -> str:
    workspace_id = _text(arguments.get("workspace_id")) or str(context.workspace_id or "").strip()
    if not workspace_id:
        raise RuntimeError("workspace_id is required.")
    return workspace_id


def _root_session(runtime_store: RuntimeStore, *, workspace_id: str, arguments: dict[str, Any]):
    root_session_id = _text(arguments.get("root_runtime_session_id"))
    return _root_session_by_id(runtime_store, workspace_id=workspace_id, session_id=root_session_id)


def _root_session_by_id(runtime_store: RuntimeStore, *, workspace_id: str, session_id: str):
    try:
        root_session = runtime_store.get_session(session_id)
    except (RuntimeSessionNotFoundError, ValueError) as error:
        raise AuthorizationError("root_runtime_session_not_found") from error
    if root_session.workspace_id != workspace_id:
        raise AuthorizationError("root_runtime_session_not_found")
    if not runtime_session_allows_user_thread(root_session):
        raise AuthorizationError("root_runtime_session_hidden")
    return root_session


def _run_has_child_runtime_participants(inter_agent_store: InterAgentStore, run) -> bool:
    return any(
        participant.execution_mode == "child_runtime_session"
        for participant in inter_agent_store.list_participants(run.run_id, workspace_id=run.workspace_id)
    )


def _text(value) -> str:
    return str(value or "").strip()


def _bool(value, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _allow_synthetic_execution(arguments: dict[str, Any], *, caller_kind: str) -> bool:
    if not _bool(arguments.get("allow_synthetic_participants"), default=False):
        return False
    if caller_kind != "operator":
        raise AuthorizationError("inter_agent_synthetic_participants_forbidden")
    return True
