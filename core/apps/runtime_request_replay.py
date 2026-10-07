"""Reconcile streamed app launches without resubmitting already admitted work."""

from core.authorization.errors import AuthorizationError
from core.runtime.app_streams import RuntimeAppStreamError


def replay_runtime_request(state, *, stream, request, actor_id, **context):
    from core.apps.runtime_requests import _invoke_runtime_request_callback, _runtime_request_fingerprint
    if stream.actor_id != actor_id:
        raise AuthorizationError("runtime_app_stream_actor_mismatch")
    if stream.request_fingerprint != _runtime_request_fingerprint(request):
        raise RuntimeAppStreamError("runtime_app_stream_idempotency_conflict")
    error = "Previous launch failed" if stream.status == "failed" else ""
    try:
        callback = _invoke_runtime_request_callback(
            state, callback=request.get("callback", {}), request=request, request_id=stream.request_id,
            status=stream.status, session_id=stream.session_id, turn_id=stream.turn_id,
            stream_id=stream.stream_id, actor_id=stream.actor_id, error=error, **context)
        callback_status = int(callback.get("status_code", 0))
    except Exception:
        # Callback failure must never change the status of an existing turn.
        callback_status = 500
    return {"request_id": stream.request_id, "status": stream.status, "stream_id": stream.stream_id,
            "runtime_session_id": stream.session_id, "turn_id": stream.turn_id, "error": error,
            "callback_status_code": callback_status, "idempotent_replay": True,
            "_visible": request.get("result_visibility") != "internal"}
