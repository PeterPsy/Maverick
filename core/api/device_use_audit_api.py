"""Owner-authenticated native evidence windows and historical screenshots."""

from urllib.parse import parse_qs

from core.api.http import json_response
from core.device_use.audit import read_device_use_call, device_use_call_image
from core.runtime.errors import RuntimeTranscriptAccessError, RuntimeTranscriptValidationError, RuntimeTurnNotFoundError
from core.runtime.runtime_threads import find_runtime_thread_by_session
from core.runtime.transcript_models import RuntimeTranscriptReadContext


def handle_device_use_audit(state, context, *, turn_id, query_string, start_response):
    try:
        turn = state.runtime_store.get_turn(turn_id)
        thread = find_runtime_thread_by_session(state.runtime_store, workspace_id=context.workspace_id,
                                               runtime_session_id=turn.session_id)
        if thread is None:
            raise RuntimeTranscriptAccessError("runtime_thread_not_found", status_code=404)
        query = parse_qs(query_string)
        call_id = query.get("call_id", [""])[0]
        archive = state.device_use_service.evidence_archive
        read_context = RuntimeTranscriptReadContext(
            workspace_id=context.workspace_id, user_id=context.user.user_id,
            platform_role=context.user.platform_role, workspace_role=None, caller_runtime_session_id=None,
        )
        arguments = dict(archive=archive, context=read_context, thread_id=thread.thread_id,
                         turn_id=turn_id, call_id=call_id)
        if query.get("image", [""])[0] == "true":
            image = device_use_call_image(state.runtime_store, **arguments)
            start_response("200 OK", [("Content-Type", "image/jpeg"), ("Cache-Control", "no-store"),
                                      ("Content-Length", str(len(image))), ("X-Content-Type-Options", "nosniff")])
            return [image]
        payload = read_device_use_call(state.runtime_store, **arguments,
                                      offset=int(query.get("offset", [0])[0]))
        return json_response(start_response, payload, headers=[("Cache-Control", "no-store")])
    except RuntimeTranscriptAccessError as error:
        return json_response(start_response, {"error": error.reason}, status=f"{error.status_code} {'Forbidden' if error.status_code == 403 else 'Not Found'}")
    except RuntimeTurnNotFoundError:
        return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
    except (RuntimeTranscriptValidationError, ValueError):
        return json_response(start_response, {"error": "device_use_audit_request_invalid"}, status="400 Bad Request")
    except Exception:
        return json_response(start_response, {"error": "device_use_evidence_unavailable"}, status="404 Not Found")
