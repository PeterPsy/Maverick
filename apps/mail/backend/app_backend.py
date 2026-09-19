"""Mounted backend entrypoint for this entity app."""

from __future__ import annotations

from pathlib import Path
import sys

for parent in Path(__file__).resolve().parents:
    if (parent / "core").is_dir():
        sys.path.insert(0, str(parent))
        break

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import app_events_for_action, handle_action, resolve_secret_resource


payload = read_entrypoint_payload()
body = dict(payload.body)
if payload.raw.get("surface") == "secret_selector":
    action = str(body.get("action") or "")
    local_actions = {"mail_create_draft", "drafts.create", "mail_update_draft", "drafts.update",
                     "mail_reference_search", "reference_search", "mail_reference_resolve", "reference_resolve",
                     "mail_reference_manifest", "reference_manifest", "drafts.get", "drafts.list"}
    selector = {"requires_secrets": False} if action in local_actions else resolve_secret_resource(Path(payload.data_root), body)
    if selector.get("requires_secrets"):
        connection = {"resource_type": "mail_connection", "resource_id": selector["resource_id"]}
        if selector.get("provider") == "gmail":
            selector["secret_requests"] = [
                {"logical_names": ["gmail-oauth-client-id", "gmail-oauth-client-secret"]},
                {"logical_names": ["gmail-refresh-token"], **connection},
            ]
        else:
            selector["secret_requests"] = [{"logical_names": ["mailbox-password"], **connection}]
    emit_json(selector)
    raise SystemExit(0)
body["_app_secrets"] = payload.raw.get("app_secrets", {})
body["_workspace_id"] = payload.workspace_id
body["_app_id"] = payload.app_id
body["_generated_storage_root"] = payload.raw.get("generated_storage_root", "")
body["_uploaded_storage_root"] = payload.raw.get("uploaded_storage_root", "")
action = str(body.get("action") or "list")
status_code, result = handle_action(Path(payload.data_root), body)
secret_writes = result.pop("platform_secret_writes", [])
response = backend_response(status_code, result)
if secret_writes:
    response["platform_secret_writes"] = secret_writes
if status_code < 400:
    response["app_events"] = app_events_for_action(action, result)
emit_json(response)
