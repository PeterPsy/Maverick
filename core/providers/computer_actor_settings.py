"""Selection and catalog for the internal PC use decision operator."""

from dataclasses import asdict
from datetime import UTC, datetime

from core.device_use.computer_actor_contract import COMPUTER_ACTOR_EFFORT, COMPUTER_ACTOR_MODEL
from core.providers.errors import ProviderSelectionError
from core.providers.models import ProviderTaskSelection
from core.providers.provider_codex import CodexProviderAdapter


COMPUTER_USE_TASK = "computer_use"


def computer_actor_selection(store, workspace_id):
    selection = store.get_task_provider_selection(workspace_id=workspace_id, task_kind=COMPUTER_USE_TASK) if store else None
    if selection is not None:
        return selection
    now = datetime.now(UTC)
    return ProviderTaskSelection(workspace_id, COMPUTER_USE_TASK, "codex", COMPUTER_ACTOR_MODEL,
                                 COMPUTER_ACTOR_EFFORT, now, now)


def computer_actor_adapter(provider_id):
    # Only integrations with an executable internal-operator contract are admitted.
    if provider_id == "codex":
        return CodexProviderAdapter()
    raise ProviderSelectionError("computer_use_provider_unavailable")


def computer_actor_model_options(adapter):
    return [option for option in adapter.model_options(require_discovery=True)
            if "image" in option.input_modalities]


def configure_computer_actor(store, *, workspace_id, provider_id, model_id, reasoning_effort,
                            execution_mode="delegated", fallback_model_id=None,
                            fallback_reasoning_effort=None):
    if execution_mode not in {"direct", "delegated"}:
        raise ProviderSelectionError("computer_use_execution_mode_invalid")
    adapter = computer_actor_adapter(provider_id)
    option = next((item for item in computer_actor_model_options(adapter) if item.model_id == model_id), None)
    if option is None:
        raise ProviderSelectionError("computer_use_model_unavailable")
    effort = reasoning_effort or ("low" if any(item.effort == "low" for item in option.supported_reasoning_efforts)
                                  else option.default_reasoning_effort)
    if effort and effort not in {item.effort for item in option.supported_reasoning_efforts}:
        raise ProviderSelectionError("computer_use_reasoning_unavailable")
    model, effort = adapter.validate_model_settings(model_id, effort)
    if fallback_model_id:
        fallback = next((item for item in computer_actor_model_options(adapter)
                         if item.model_id == fallback_model_id), None)
        if (fallback is None or fallback_model_id == model_id or execution_mode == "direct"
            or fallback_reasoning_effort not in {item.effort for item in fallback.supported_reasoning_efforts}):
            raise ProviderSelectionError("computer_use_fallback_invalid")
        adapter.validate_model_settings(fallback_model_id, fallback_reasoning_effort)
    elif fallback_reasoning_effort:
        raise ProviderSelectionError("computer_use_fallback_invalid")
    previous = store.get_task_provider_selection(workspace_id=workspace_id, task_kind=COMPUTER_USE_TASK)
    now = datetime.now(UTC)
    return store.save_task_provider_selection(ProviderTaskSelection(
        workspace_id, COMPUTER_USE_TASK, provider_id, model, effort,
        previous.created_at if previous else now, now,
        execution_mode, fallback_model_id, fallback_reasoning_effort,
    ))


def validate_computer_actor_selection(selection):
    if selection.execution_mode not in {"delegated", "direct"}:
        raise ProviderSelectionError("computer_use_execution_mode_invalid")
    adapter = computer_actor_adapter(selection.provider_id)
    option = next((item for item in computer_actor_model_options(adapter) if item.model_id == selection.model_id), None)
    if option is None:
        raise ProviderSelectionError("computer_use_model_unavailable")
    supported = {item.effort for item in option.supported_reasoning_efforts}
    if (supported and selection.reasoning_effort not in supported) or (not supported and selection.reasoning_effort):
        raise ProviderSelectionError("computer_use_reasoning_unavailable")
    adapter.validate_model_settings(selection.model_id, selection.reasoning_effort)
    if selection.fallback_model_id:
        fallback = next((item for item in computer_actor_model_options(adapter)
                         if item.model_id == selection.fallback_model_id), None)
        if (fallback is None or selection.execution_mode != "delegated"
            or selection.fallback_model_id == selection.model_id
            or selection.fallback_reasoning_effort not in {item.effort for item in fallback.supported_reasoning_efforts}):
            raise ProviderSelectionError("computer_use_fallback_invalid")


def computer_actor_settings_payload(store, workspace_id, *, can_configure=False):
    selection = computer_actor_selection(store, workspace_id)
    adapter = computer_actor_adapter("codex")
    options = computer_actor_model_options(adapter)
    selected = next((option for option in options if option.model_id == selection.model_id), None)
    available = selection.provider_id == "codex" and selected is not None
    if available:
        supported = {item.effort for item in selected.supported_reasoning_efforts}
        available = selection.reasoning_effort in supported if supported else not selection.reasoning_effort
    return {
        "workspace_id": workspace_id,
        "provider_id": selection.provider_id, "model_id": selection.model_id,
        "reasoning_effort": selection.reasoning_effort, "can_configure": can_configure,
        "execution_mode": selection.execution_mode,
        "fallback_model_id": selection.fallback_model_id,
        "fallback_reasoning_effort": selection.fallback_reasoning_effort,
        "available": available, "unavailable_reason": None if available else "computer_use_model_unavailable",
        "providers": [{"provider_id": "codex", "label": "Codex", "models": [asdict(option) for option in options]}],
    }
