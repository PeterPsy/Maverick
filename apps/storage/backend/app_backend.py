"""Storage app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from errors import StorageConflictError, StorageValidationError, conflict_error_payload, validation_error_payload
from operations_manifest import STORAGE_ACTION_ALIASES
from service import app_events_for_result, handle_action, prepare_media_response_body, secret_lookup_for_drive_action, stream_prepared_media_response_body


def _response(status_code: int, payload: dict) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body, media_route = _body_from_payload(payload)
    body = {
        **body,
        "_app_secrets": payload.get("app_secrets", {}),
        "_workspace_id": payload.get("workspace_id") or "default",
        "_app_id": payload.get("app_id") or "storage",
        "_consumer_app_id": str(payload.get("consumer_app_id") or ""),
        "_dependency_alias": str(payload.get("dependency_alias") or ""),
        "_surface": str(payload.get("surface") or "backend"),
        "_effective_mode": str(payload.get("effective_mode") or "sandbox"),
    }
    requested_action = str(body.get("action") or "catalog")
    action = STORAGE_ACTION_ALIASES.get(requested_action, requested_action)
    body = {**body, "action": action}
    if payload.get("surface") == "secret_selector":
        print(
            json.dumps(
                secret_lookup_for_drive_action(
                    Path(payload["data_root"]),
                    Path(payload["uploaded_storage_root"]),
                    Path(payload["generated_storage_root"]),
                    body,
                ),
                ensure_ascii=False,
            )
        )
        return
    try:
        status_code, result = handle_action(
            Path(payload["data_root"]),
            Path(payload["uploaded_storage_root"]),
            Path(payload["generated_storage_root"]),
            body,
            allow_platform_secret_writes=True,
            media_route=media_route,
            media_request_method=str(payload.get("method") or "GET").upper(),
            streaming_response_supported=media_route and str(payload.get("stream_response_protocol") or "") == "maverick.backend.stream.v1",
        )
    except StorageConflictError as error:
        _response(409, conflict_error_payload(error))
        return
    except StorageValidationError as error:
        _response(400, validation_error_payload(error))
        return
    app_events = app_events_for_result(action, result) if status_code < 400 else []
    stream_plan = result.pop("drive_stream", None)
    if isinstance(stream_plan, dict) and media_route and str(payload.get("stream_response_protocol") or "") == "maverick.backend.stream.v1":
        stream_response = result.pop("stream_response", None)
        if not isinstance(stream_response, dict):
            _response(500, {"error": "stream_response_missing"})
            return
        try:
            prepared_stream = prepare_media_response_body(
                data_root=Path(payload["data_root"]),
                uploaded_root=Path(payload["uploaded_storage_root"]),
                generated_root=Path(payload["generated_storage_root"]),
                body=body,
                stream_plan=stream_plan,
            )
        except StorageValidationError as error:
            _response(400, validation_error_payload(error))
            return
        sys.stdout.buffer.write(json.dumps({"status_code": status_code, "stream_response": stream_response}, ensure_ascii=False).encode("utf-8") + b"\n")
        sys.stdout.buffer.flush()
        stream_prepared_media_response_body(
            prepared_stream,
            output_handle=sys.stdout.buffer,
        )
        return
    platform_secret_writes = result.pop("platform_secret_writes", None)
    response = {"status_code": status_code}
    file_response = result.pop("file_response", None)
    if isinstance(file_response, dict):
        response["file_response"] = file_response
        if result:
            response["json"] = result
    else:
        stream_response = result.pop("stream_response", None)
        if isinstance(stream_response, dict):
            response["stream_response"] = stream_response
            if result:
                response["json"] = result
        else:
            response["json"] = result
    if platform_secret_writes is not None:
        response["platform_secret_writes"] = platform_secret_writes
    if status_code < 400:
        response["app_events"] = app_events
    print(json.dumps(response, ensure_ascii=False))


def _body_from_payload(payload: dict) -> tuple[dict, bool]:
    route_path = str(payload.get("route_path") or "")
    method = str(payload.get("method") or "").upper()
    if method in {"GET", "HEAD"} and route_path.startswith("/api/apps/") and route_path.endswith("/media"):
        query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
        headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
        action = "folder.media_stream" if str(query.get("media_kind") or "").strip() == "folder" else "file.media_stream"
        return {**query, "_request_headers": headers, "action": action}, True
    return payload.get("body") if isinstance(payload.get("body"), dict) else {}, False


if __name__ == "__main__":
    main()
