"""Exclusive, cancellable inference and callback delivery for app tasks."""

from __future__ import annotations

import fcntl
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock, Thread

from core.api.app_event_publication import declared_data_event_resources, publish_declared_app_events
from core.apps.errors import AppHostingError
from core.providers.background_text import generate_background_text
from core.shared.entrypoints import EntrypointShutdownController, run_json_entrypoint

_active = {}
_guard = RLock()


def apply_background_generation_requests(state, *, result, workspace_id, app_id,
                                         source_root, backend_entrypoint, data_root,
                                         parsed, start_path, actor_user_id=None):
    requests = result.pop("background_generation_requests", [])
    cancellations = result.pop("background_generation_cancel_requests", [])
    if not requests and not cancellations:
        return
    if not parsed.contract.permissions.runtime.create_sessions or backend_entrypoint is None:
        raise AppHostingError("background_generation_permission_required")
    if not isinstance(requests, list) or len(requests) > 1 or not isinstance(cancellations, list):
        raise AppHostingError("background_generation_requests_invalid")
    for request_id in cancellations:
        with _guard:
            controller = _active.get((workspace_id, app_id, str(request_id)))
        if controller:
            controller.begin_shutdown()
    context = dict(state=state, workspace_id=workspace_id, app_id=app_id,
                   source_root=source_root, backend_entrypoint=backend_entrypoint,
                   data_root=data_root, parsed=parsed, start_path=start_path,
                   actor_user_id=actor_user_id)
    for raw in requests:
        request = validate_request(raw)
        owner = getattr(state, "background_generation_shutdown_controller", None)
        if owner is None or owner.is_shutting_down():
            _callback(context, request, {"status": "failed", "error": "background_host_unavailable"})
            continue
        directory = Path(state.repository_root) / "data/control-plane/background-generation"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (sha256(request["exclusive_key"].encode()).hexdigest() + ".lock")
        handle = path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            _callback(context, request, {"status": "busy"})
            continue
        controller = EntrypointShutdownController()
        key = (workspace_id, app_id, request["request_id"])
        with _guard:
            _active[key] = controller
        if owner:
            owner.register_cleanup(controller.begin_shutdown)
        Thread(target=_run, kwargs=dict(context=context, request=request, handle=handle,
                                       controller=controller, owner=owner, key=key),
               name=f"background-generation-{app_id}", daemon=True).start()


def validate_request(raw):
    if not isinstance(raw, dict):
        raise AppHostingError("background_generation_request_invalid")
    request = dict(raw)
    for name, limit in (("request_id", 128), ("exclusive_key", 128),
                        ("system_prompt", 16_000), ("input_text", 100_000)):
        if not isinstance(request.get(name), str) or not 0 < len(request[name]) <= limit:
            raise AppHostingError(f"background_generation_{name}_invalid")
    for name, default, low, high in (("timeout_seconds", 120, 10, 300),
                                   ("max_output_tokens", 2048, 128, 8192)):
        value = request.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise AppHostingError(f"background_generation_{name}_invalid")
        request[name] = value
    if request.get("model_source", "workspace") not in {"workspace", "fast_model"}:
        raise AppHostingError("background_generation_model_source_invalid")
    if request.get("reasoning_effort", "low") not in {"low", "medium", "high"}:
        raise AppHostingError("background_generation_reasoning_invalid")
    if not isinstance(request.get("output_schema"), dict) or len(json.dumps(request["output_schema"])) > 32_000:
        raise AppHostingError("background_generation_schema_invalid")
    if not isinstance(request.get("callback"), dict) or not request["callback"].get("action"):
        raise AppHostingError("background_generation_callback_required")
    if not isinstance(request.get("model_id", ""), str) or len(request.get("model_id", "")) > 240:
        raise AppHostingError("background_generation_model_id_invalid")
    callback = request["callback"]
    if not isinstance(callback["action"], str) or len(callback["action"]) > 128 or not isinstance(callback.get("payload", {}), dict):
        raise AppHostingError("background_generation_callback_invalid")
    admission = request.get("admission")
    if admission is not None and (not isinstance(admission, dict) or not isinstance(admission.get("action"), str)
                                  or not 0 < len(admission["action"]) <= 128 or not isinstance(admission.get("payload", {}), dict)):
        raise AppHostingError("background_generation_admission_invalid")
    return request


def _run(*, context, request, handle, controller, owner, key):
    try:
        if controller.is_shutting_down():
            _callback(context, request, {"status": "cancelled"})
            return
        admission = request.get("admission")
        if admission:
            result = _invoke_app(context, "background_generation_admission", {
                **admission.get("payload", {}), "action": admission["action"], "request_id": request["request_id"]})
            if result.get("json", {}).get("allowed") is not True or controller.is_shutting_down():
                _callback(context, request, {"status": "cancelled"})
                return
        output = generate_background_text(context["state"], workspace_id=context["workspace_id"],
                                         app_id=context["app_id"], request=request,
                                         controller=controller, lock_fd=handle.fileno())
        if controller.is_shutting_down():
            output = {"status": "cancelled"}
        else:
            output["status"] = "completed"
        _callback(context, request, output)
    except Exception as error:
        # Arbitrary provider exceptions may contain private prompt/credential data.
        try:
            _callback(context, request, {"status": "cancelled" if controller.is_shutting_down() else "failed",
                                         "error": _safe_error(error)})
        except Exception:
            pass  # App recovery reconciles the persisted attempt.
    finally:
        if owner:
            owner.unregister_cleanup(controller.begin_shutdown)
        with _guard:
            _active.pop(key, None)
        handle.close()


def _callback(context, request, output):
    callback = request["callback"]
    result = _invoke_app(context, "background_generation_callback", {
        **callback.get("payload", {}), "action": callback["action"], "request_id": request["request_id"], **output})
    if int(result.get("status_code", 200)) >= 400:
        raise AppHostingError("background_generation_callback_failed")
    publish_declared_app_events(context["state"].app_event_bus, result,
        workspace_id=context["workspace_id"], app_id=context["app_id"],
        declared_resources=declared_data_event_resources(context["parsed"].contract.capabilities.data_events),
        remove_from_result=True)
    from core.apps.runtime_requests import apply_app_runtime_requests
    apply_app_runtime_requests(**context, result=result)


def _invoke_app(context, surface, body):
    return run_json_entrypoint(Path(context["source_root"]) / context["backend_entrypoint"],
        payload={"surface": surface, "workspace_id": context["workspace_id"],
                 "app_id": context["app_id"], "data_root": context["data_root"], "body": body},
        cwd=Path(context["source_root"]), timeout_seconds=30,
        shutdown_controller=getattr(context["state"], "background_generation_shutdown_controller", None))


def _safe_error(error):
    code = str(getattr(error, "reason_code", "") or "")
    message = str(error)
    if not code and message.startswith("background_") and message.replace("_", "").isalnum() and len(message) <= 128:
        code = message
    return code or "background_generation_failed"
