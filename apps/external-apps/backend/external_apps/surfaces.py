"""Closed action schemas and trusted-envelope entrypoint adapters."""
from pathlib import Path
import sqlite3

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

from .context import from_envelope
from .errors import AppError
from .service import ACTIONS, READS, Service

FIELDS = {
    "operations.manifest": set(), "health": set(),
    "list": {"query", "status", "offset", "limit"},
    "get": {"external_app_id", "plan_id"},
    "publish.plan": {"external_app_id", "source_entity_id", "build_id", "name", "format"},
    "rollback.plan": {"external_app_id"},
    "publish.apply": {"plan_id", "plan_digest", "confirm", "idempotency_key"},
    "rollback.apply": {"plan_id", "plan_digest", "confirm", "idempotency_key"},
    "suspend": {"external_app_id", "expected_generation", "confirm", "idempotency_key"},
    "archive": {"external_app_id", "expected_generation", "confirm", "idempotency_key"},
    "deployment.configure": {"installation_domain"},
    "plan.approve": {"plan_id", "plan_digest", "confirm"},
}


def validate(body, *, backend=False):
    action = body.get("action", "operations.manifest")
    if action not in (ACTIONS | {"plan.approve"} if backend else ACTIONS):
        raise AppError("unsupported_action")
    if set(body) - (FIELDS[action] | {"action"}):
        raise AppError("unexpected_argument")
    for key, value in body.items():
        if key in {"limit", "offset", "expected_generation"}:
            if type(value) is not int or value < 0:
                raise AppError("invalid_argument")
        elif key == "confirm":
            if type(value) is not bool:
                raise AppError("invalid_argument")
        elif not isinstance(value, str) or len(value) > 256:
            raise AppError("invalid_argument")
    return {**body, "action": action}


def run(surface):
    payload = read_entrypoint_payload()
    body = payload.body if surface == "backend" else payload.arguments
    try:
        ctx = from_envelope(payload)
        if (surface == "mcp" and payload.raw.get("tool_name") == "external_apps_reference_manifest") or (surface == "cli" and body.get("action") == "references.manifest"):
            allowed = {"action"} if surface == "cli" else set()
            if set(body) - allowed:
                raise AppError("unexpected_argument")
            # Static SDK schema metadata only: no actor, catalog or data access.
            emit_json({"status_code": 200, "app_id": payload.app_id, "entity_types": [], "supported": False})
            return
        if payload.raw.get("surface") == "secret_selector":
            result, code = {"requires_secrets": False}, 200
        else:
            if ctx.surface != "dependency_backend_request_callback":
                body = validate(body, backend=surface == "backend")
            elif surface != "backend" or body.get("action") != "export.completed":
                raise AppError("invalid_callback_surface", 403)
            result = Service(Path(payload.data_root), ctx).handle(body)
            code = 200
    except AppError as error:
        result, code = {"error_code": error.code}, error.status
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        result, code = {"error_code": "operation_failed"}, 500
    response = backend_response(code, result) if surface == "backend" else {"status_code": code, **result}
    if code < 400 and body.get("action") not in READS:
        response["app_events"] = [{"type": "maverick.app.data-changed", "resource": "state"}]
    emit_json(response)
