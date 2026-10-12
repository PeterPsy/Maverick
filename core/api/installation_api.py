"""Authenticated installation administration and a bounded public host proof."""

from datetime import datetime, timedelta, timezone
import os

from core.api.http import json_response, read_json_body, status_line
from core.api.session_api import RequestSession, require_session
from core.installation.address_redirect import document_redirect
from core.api.app_frame_scope import APP_FRAME_PROXY_SCOPE_KEY
from core.installation.errors import InstallationError
from core.installation.operations import OPERATIONS, invoke
from core.installation.service import InstallationService
from core.installation.validation import record_id
from core.observability.service import record_platform_audit


def service_for_state(state):
    return InstallationService(state.repository_root, secret_store=state.secret_store,
        app_store=state.app_store, workspace_store=state.workspace_store)


def handle_installation_api(state, environ, start_response):
    path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
    if path.startswith("/api/installation/probe/"):
        if method != "GET":
            return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
        try:
            identifier = record_id(path.removeprefix("/api/installation/probe/"))
            job = service_for_state(state).store.read("jobs", identifier)
            if not job or datetime.fromisoformat(job["updated_at"]) < datetime.now(timezone.utc) - timedelta(minutes=15):
                raise InstallationError("probe_not_found", status=404)
            return json_response(start_response, {"nonce": job["probe_nonce"],
                "hostname": os.environ.get("MAVERICK_SIDECAR_INSTALLATION_DOMAIN", "")})
        except (InstallationError, KeyError, ValueError):
            return json_response(start_response, {"error": "probe_not_found"}, status="404 Not Found")
    prefix = "/api/admin/installation"
    if path != prefix and not path.startswith(prefix + "/"):
        return None
    context = require_session(state, environ, start_response)
    if not isinstance(context, RequestSession):
        return context
    if context.user.platform_role != "admin":
        return json_response(start_response, {"error": "admin_required"}, status="403 Forbidden")
    operation = path.removeprefix(prefix).strip("/") or "inspect"
    if method != ("GET" if operation in {"inspect", "verify"} else "POST"):
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    try:
        arguments = read_json_body(environ) if method == "POST" else {}
        result = invoke(service_for_state(state), operation, arguments, actor_user_id=context.user.user_id)
        if OPERATIONS[operation][2] != "read":
            record_platform_audit(state.observability_store, action="core.installation." + operation,
                status="succeeded", source_domain="installation", detail="Installation administration",
                payload={"actor_user_id": context.user.user_id, "operation": operation})
        return json_response(start_response, result)
    except InstallationError as error:
        return json_response(start_response, {"error": error.code}, status=status_line(error.status))
    except Exception:
        return json_response(start_response, {"error": "installation_operation_failed"}, status="503 Service Unavailable")


def handle_installation_document_redirect(state, environ, start_response):
    path = environ.get("PATH_INFO", "/")
    if path not in {"/", "/app"} and not path.startswith("/app/"):
        return None
    location = document_redirect(service_for_state(state).configuration(), path=path,
        request_host=environ.get("HTTP_HOST", ""), method=environ.get("REQUEST_METHOD", "GET"),
        query=environ.get("QUERY_STRING", ""), app_frame=environ.get(APP_FRAME_PROXY_SCOPE_KEY) is True)
    if location is None:
        return None
    start_response("308 Permanent Redirect", [("Location", location), ("Cache-Control", "no-store"), ("Content-Length", "0")])
    return [b""]
