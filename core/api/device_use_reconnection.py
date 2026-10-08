"""Explicit native lease renewal for an idle, already admitted conversation."""

from core.device_use.errors import DeviceUseAuthorizationError, DeviceUseUnavailableError
from core.device_use.runtime_registry import register_device_use_session
from core.device_use.contract import DEVICE_USE_EXECUTOR_CONTRACT, DEVICE_USE_TOOL_CONTRACT_DIGEST
from core.runtime.errors import RuntimeProviderStateError, RuntimeSessionNotFoundError
from core.runtime.agentic_runtime_service import update_runtime_provider_state
from core.runtime.runtime_process_lifecycle import ACTIVE_TURN_STATUSES, release_idle_runtime_processes
from core.runtime.runtime_threads import find_runtime_thread_by_session
from core.runtime.thread_catalog_events import publish_runtime_thread_catalog_change


def reconnect_device_use_session(
    state, *, session_id: str, owner_user_id: str, workspace_id: str,
    auth_session_id: str, activation_id: str, previous_activation_id: str,
) -> dict[str, object]:
    """Renew physical transport without changing the conversation's authority."""
    store = state.runtime_store
    service = state.device_use_service
    with store.session_lifecycle_handoff(workspace_id=workspace_id, session_id=session_id):
        try:
            session = store.get_session(session_id)
        except RuntimeSessionNotFoundError as error:
            raise DeviceUseAuthorizationError("device_use_session_forbidden") from error
        previous = session.device_use_binding
        if (
            session.workspace_id != workspace_id
            or session.owner_user_id != owner_user_id
            or previous is None
            or previous.owner_user_id != owner_user_id
            or previous.workspace_id != workspace_id
            or session.session_kind != "chat_root"
        ):
            raise DeviceUseAuthorizationError("device_use_session_forbidden")
        if previous.activation_id != previous_activation_id:
            raise DeviceUseAuthorizationError("device_use_binding_changed")
        if session.status not in {"created", "running"}:
            raise DeviceUseUnavailableError("device_use_session_stopped")
        if any(turn.status in ACTIVE_TURN_STATUSES for turn in store.list_turns(session_id)):
            raise DeviceUseUnavailableError("device_use_session_busy")
        binding = service.binding_snapshot(
            activation_id, owner_user_id=owner_user_id, workspace_id=workspace_id,
            auth_session_id=auth_session_id,
        )
        if (
            binding.mode != previous.mode
            or binding.protocol_version != previous.protocol_version
            or not _renewable_contract(previous, binding)
            or (binding.mode == "on" and (
                binding.initial_app != previous.initial_app
                or set(binding.approved_apps) != set(previous.approved_apps)
            ))
        ):
            raise DeviceUseAuthorizationError("device_use_reconnect_scope_changed")
        # Retire any idle provider carrying the old binding before publishing the
        # new one. The lifecycle fence also excludes concurrent queue admission.
        release_idle_runtime_processes(
            state, session_id=session_id, provider_id=session.provider_id,
            reason="device_use_reconnected", idle_ttl_seconds=0,
        )
        service.bind_session(binding, session_id=session_id)
        try:
            store.replace_session_device_use_lease(
                session_id=session_id, workspace_id=workspace_id,
                expected_activation_id=previous.activation_id, binding=binding,
            )
            # A renewed native lease starts a fresh provider context: archived
            # tool calls and receipts belong to the previous activation. Keep
            # the execution binding and restore visible text through governed
            # provider-input capture on the next turn.
            update_runtime_provider_state(store, session_id=session_id, updates={
                "provider_thread_id": None, "continuation_id": None,
                "provider_request_id": None, "turn_generation": None,
            })
        except Exception as error:
            service.stop_activation(activation_id, reason="device_use_reconnect_failed")
            if isinstance(error, RuntimeProviderStateError):
                raise DeviceUseAuthorizationError("device_use_binding_changed") from error
            raise
        register_device_use_session(session_id, service, activation_id=activation_id)
        service.stop_activation(previous.activation_id, reason="device_use_reconnected")
        thread = find_runtime_thread_by_session(store, workspace_id=workspace_id, runtime_session_id=session_id)
        if thread is not None:
            publish_runtime_thread_catalog_change(state, workspace_id=workspace_id, action="updated", thread=thread)
        return service.public_activation(
            activation_id, owner_user_id=owner_user_id, workspace_id=workspace_id,
            auth_session_id=auth_session_id,
        )


def _renewable_contract(previous, binding):
    if (previous.executor_contract, previous.tool_contract_digest) == (binding.executor_contract, binding.tool_contract_digest):
        return True
    # Reviewed additive companion upgrade: explicit idle reconnection retires the old
    # provider context. Owner, workspace, protocol and On/Full scope stay fixed.
    return (previous.executor_contract, previous.tool_contract_digest) in {
        ("macos-v49", "eb8c2b9ca42c9c03ee516283fd39490d1ca5957d89c665bade60c126a1169abf"),
        ("macos-v48", "5682ddabb352ada6e227e2294e8026ae3f47ce095e3de9466aab11627d6a5b8d"),
        ("macos-v47", "d0405d09ac1ff6903336a7fa7427c7c28e2922167a0dfe302a4db0bc48b00c71"),
        ("macos-v44", "d525d61fc31a5d873b189166be26d90bd613dc1e2e430f69a07744d920ea4dd1"),
        ("macos-v46", "776dd4eeb79c7eca35ddda4475d6c412401987cebdd1f14fab34d1ef5345c7fb"),
        ("macos-v45", "0b96e1a3013c1bfece055623d8b104cd029b1b8ebb21719686999531abbf424d"),
    } and (binding.executor_contract, binding.tool_contract_digest) == (
        DEVICE_USE_EXECUTOR_CONTRACT, DEVICE_USE_TOOL_CONTRACT_DIGEST)
