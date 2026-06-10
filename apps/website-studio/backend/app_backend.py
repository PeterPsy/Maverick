"""Mounted backend entrypoint for this entity app."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from urllib.parse import urlparse

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import app_events_for_action, handle_action


def _request_origin(raw_headers: object) -> str:
    if not isinstance(raw_headers, dict):
        return ""
    headers = {str(key).lower(): str(value).strip() for key, value in raw_headers.items()}
    origin = _clean_origin(headers.get("origin"))
    if origin:
        return origin
    host = headers.get("x-forwarded-host") or headers.get("host") or ""
    proto = (headers.get("x-forwarded-proto") or headers.get("x-forwarded-scheme") or "http").split(",")[0].strip().lower()
    if proto not in {"http", "https"} or not host:
        return ""
    return _clean_origin(f"{proto}://{host.split(',')[0].strip()}")


def _entrypoint_headers(raw_payload: object) -> object:
    if not isinstance(raw_payload, dict):
        return {}
    headers = raw_payload.get("headers")
    if isinstance(headers, dict):
        return headers
    nested_raw = raw_payload.get("raw")
    if isinstance(nested_raw, dict) and isinstance(nested_raw.get("headers"), dict):
        return nested_raw["headers"]
    return {}


def _clean_origin(value: object) -> str:
    text = str(value or "").strip()
    if not text or any(char in text for char in "\r\n\t"):
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


payload = read_entrypoint_payload()
request_body = dict(payload.body)
route_path = str(payload.raw.get("route_path") or "")
method = str(payload.raw.get("method") or "").upper()
if method in {"GET", "HEAD"} and route_path.startswith("/api/apps/") and route_path.endswith("/backend/media"):
    query = payload.raw.get("query") if isinstance(payload.raw.get("query"), dict) else {}
    request_body = {**query, "action": "preview_media"}

action = str(request_body.get("action") or "sites_list")
if action in {"build_preview", "preview_document", "preview_report"}:
    preview_origin = _request_origin(_entrypoint_headers(payload.raw))
    if preview_origin:
        request_body["_preview_origin"] = preview_origin
body = {
    **request_body,
    "_app_actor": {
        "user_id": payload.user_id,
        "workspace_role": payload.workspace_role,
        "platform_role": payload.platform_role,
        "effective_mode": payload.effective_mode,
    },
    "_app_secrets": dict(payload.raw.get("app_secrets") or {}),
    "_app_secret_errors": list(payload.raw.get("app_secret_errors") or []),
}
status_code, result = handle_action(Path(payload.data_root), body)
response = {"status_code": status_code}
response_payload = dict(result)
file_response = response_payload.pop("file_response", None)
if isinstance(file_response, dict):
    response["file_response"] = file_response
    if response_payload:
        response["json"] = response_payload
else:
    response = backend_response(status_code, result)
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
if method in {"GET", "HEAD"}:
    sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
else:
    emit_json(response)
