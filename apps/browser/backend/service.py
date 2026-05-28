"""Browser app controller for P0 policy, state, audit, and broker handoff."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from core.egress import evaluate_browser_egress_url, resolve_browser_egress_url_addresses

from broker_client import broker_health, call_broker_action
from errors import BrowserBrokerUnavailableError, BrowserPolicyError, BrowserValidationError
from models import AUDITED_ACTIONS, DEV_INSPECTOR_ACTIONS, MCP_TOOL_ACTIONS, READ_ONLY_ACTIONS
from store import append_audit_record, load_state, remove_session_record, save_state, upsert_session_record


SESSION_ACTIONS = AUDITED_ACTIONS - {"session.create"}
ACTION_EVENTS = AUDITED_ACTIONS
FORBIDDEN_PROFILE_FIELDS = frozenset(
    {
        "accept_downloads",
        "acceptDownloads",
        "download_path",
        "downloadPath",
        "downloads_path",
        "downloadsPath",
        "file",
        "files",
        "file_path",
        "filePath",
        "profile",
        "profile_id",
        "profileId",
        "storage_state",
        "storageState",
        "upload",
        "uploads",
        "user_data_dir",
        "userDataDir",
    }
)
FORBIDDEN_TRUSTED_FIELDS = frozenset(
    {"allow_admin_dev_targets", "caller_context", "policy_context", "resolved_addresses"}
)
FORBIDDEN_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_id",
        "artifact_path",
        "download",
        "downloads",
        "persist",
        "persisted",
        "save",
        "storage_path",
        "storagePath",
    }
)
P0_ACTION_FIELDS = {
    "session.create": frozenset({"action", "mode"}),
    "session.close": frozenset({"action", "session_id"}),
    "navigate": frozenset({"action", "session_id", "url", "mode"}),
    "snapshot": frozenset({"action", "session_id"}),
    "screenshot": frozenset({"action", "session_id", "full_page"}),
    "console.messages": frozenset({"action", "session_id", "limit"}),
    "network.requests": frozenset({"action", "session_id", "limit"}),
    "tabs": frozenset({"action", "session_id"}),
    "wait_for": frozenset({"action", "session_id", "state", "timeout_ms"}),
    "click": frozenset({"action", "session_id", "ref", "target_url", "mode"}),
    "type": frozenset({"action", "session_id", "ref", "text", "target_url", "mode"}),
    "press_key": frozenset({"action", "session_id", "key", "target_url", "mode"}),
}
ACCEPTANCE_URL_ENV = "MAVERICK_BROWSER_ACCEPTANCE_URL"
DEFAULT_ACCEPTANCE_URL = "https://example.com/"


def app_events_for_action(action: str) -> list[dict[str, str]]:
    if action in ACTION_EVENTS:
        return [{"type": "maverick.app.data-changed", "resource": "state"}]
    return []


def handle_action(
    data_root: Path,
    body: dict[str, Any],
    *,
    workspace_id: str | None = None,
    app_id: str = "browser",
    effective_mode: str | None = None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "status").strip()
    admin_dev_targets_enabled = is_admin_authority(platform_role=platform_role, workspace_role=workspace_role)
    try:
        if action in {"status", "operations.manifest"}:
            result = status_payload(
                data_root,
                app_id=app_id,
                workspace_id=workspace_id,
                admin_dev_targets_enabled=admin_dev_targets_enabled,
            )
            if action == "operations.manifest":
                result["operations"] = operations_manifest()
            return 200, result
        if action == "policy.preflight":
            policy = preflight_payload(body, admin_dev_targets_enabled=admin_dev_targets_enabled)
            return 200, {"policy": policy}
        if action == "audit.list":
            state = load_state(str(data_root))
            audit = visible_audit_records(state, admin_dev_targets_enabled=admin_dev_targets_enabled)
            return 200, {"audit": audit, "limit": len(audit)}
        if action in AUDITED_ACTIONS:
            status_code, result = broker_action_result(
                data_root,
                action,
                body,
                workspace_id=workspace_id,
                admin_dev_targets_enabled=admin_dev_targets_enabled,
            )
            audit_browser_action(
                data_root,
                action,
                body,
                status="ok" if status_code < 400 else "failed",
                reason=result.get("error"),
                mode=str(result.get("mode") or ""),
            )
            return status_code, result
    except BrowserValidationError as error:
        if action in AUDITED_ACTIONS:
            audit_browser_action(data_root, action, body, status="invalid", reason="validation_error")
        return 400, {"error": "validation_error", "detail": str(error), "field": error.field}
    except BrowserPolicyError as error:
        audit_browser_action(data_root, action, body, status="denied", reason=error.decision.get("reason"))
        return 403, {"error": "policy_denied", "detail": str(error), "policy": error.decision}
    except BrowserBrokerUnavailableError as error:
        audit_browser_action(data_root, action, body, status="blocked", reason="broker_unavailable")
        return 503, {"error": "broker_unavailable", "detail": str(error), "action": action}
    return 400, {"error": "unsupported_action", "detail": f"Unsupported Browser action: {action}.", "action": action}


def mcp_result_for_tool(
    data_root: Path,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    workspace_id: str | None = None,
    app_id: str = "browser",
    effective_mode: str | None = None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
) -> tuple[int, dict[str, Any]]:
    action = MCP_TOOL_ACTIONS.get(tool_name)
    if action is None:
        return 400, {
            "error": "unsupported_tool",
            "detail": f"Unsupported Browser MCP tool: {tool_name or '<empty>'}.",
            "allowed_values": {"tool_name": sorted(MCP_TOOL_ACTIONS)},
        }
    if "action" in arguments:
        return 400, {
            "error": "validation_error",
            "detail": "action is derived from the Browser MCP tool name and cannot be supplied by callers.",
            "field": "action",
        }
    return handle_action(
        data_root,
        {"action": action, **arguments},
        workspace_id=workspace_id,
        app_id=app_id,
        effective_mode=effective_mode,
        platform_role=platform_role,
        workspace_role=workspace_role,
    )


def status_payload(
    data_root: Path,
    *,
    app_id: str,
    workspace_id: str | None,
    admin_dev_targets_enabled: bool,
) -> dict[str, Any]:
    state = load_state(str(data_root))
    broker = dict(state["broker"])
    live_health = broker_health()
    broker.update(live_health)
    if "detail" not in live_health and broker.get("status") == "ready":
        broker.pop("detail", None)
    sessions = visible_session_records(state, admin_dev_targets_enabled=admin_dev_targets_enabled)
    audit = visible_audit_records(state, admin_dev_targets_enabled=admin_dev_targets_enabled)
    return {
        "app_id": app_id,
        "workspace_id": workspace_id,
        "schema_version": state["schema_version"],
        "broker": broker,
        "session_count": len(sessions),
        "sessions": sessions,
        "audit_count": len(audit),
        "p0_scope": {
            "browser_lab_read_only": True,
            "maverick_dev_inspector": True,
            "chrome_companion": False,
            "persistent_profiles": False,
            "file_upload": False,
            "automatic_download_persistence": False,
            "arbitrary_code_evaluation": False,
        },
    }


def visible_session_records(state: dict[str, Any], *, admin_dev_targets_enabled: bool) -> list[dict[str, Any]]:
    sessions = state.get("sessions")
    if not isinstance(sessions, dict):
        return []
    records = [record for record in sessions.values() if isinstance(record, dict)]
    if admin_dev_targets_enabled:
        return records
    return [record for record in records if record.get("mode") != "maverick_dev_inspector"]


def visible_audit_records(state: dict[str, Any], *, admin_dev_targets_enabled: bool) -> list[dict[str, Any]]:
    audit = state.get("audit")
    if not isinstance(audit, list):
        return []
    records = [record for record in audit if isinstance(record, dict)]
    if admin_dev_targets_enabled:
        return records
    dev_session_ids = {
        str(record.get("session_id"))
        for record in visible_session_records(state, admin_dev_targets_enabled=True)
        if record.get("mode") == "maverick_dev_inspector" and record.get("session_id")
    }
    return [
        record
        for record in records
        if record.get("mode") != "maverick_dev_inspector" and str(record.get("session_id") or "") not in dev_session_ids
    ]


def operations_manifest() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "modes": {
            "read_only": {
                "actions": sorted(READ_ONLY_ACTIONS),
                "description": "Navigate, observe snapshots, screenshots, tabs, console, and network metadata under core egress policy.",
            },
            "maverick_dev_inspector": {
                "actions": sorted(READ_ONLY_ACTIONS | DEV_INSPECTOR_ACTIONS),
                "description": "Adds click, type, and key press only for admin-enabled Maverick dev targets.",
            },
        },
        "mcp_tools": sorted(MCP_TOOL_ACTIONS),
        "disabled": [
            "browser_evaluate",
            "browser_run_code",
            "storage_state_import",
            "storage_state_export",
            "file_upload",
            "automatic_download_persistence",
        ],
    }


def acceptance_smoke_payload(
    data_root: Path,
    body: dict[str, Any],
    *,
    workspace_id: str | None = None,
    app_id: str = "browser",
    effective_mode: str | None = None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run the P0 broker acceptance path through the same controller surface agents use."""

    target_url = str(body.get("url") or os.environ.get(ACCEPTANCE_URL_ENV) or DEFAULT_ACCEPTANCE_URL).strip()
    if not target_url:
        raise BrowserValidationError("url is required.", field="url")
    mode = str(body.get("mode") or "read_only").strip()
    if mode not in {"read_only", "maverick_dev_inspector"}:
        raise BrowserValidationError("mode must be read_only or maverick_dev_inspector.", field="mode")
    admin_dev_targets_enabled = is_admin_authority(platform_role=platform_role, workspace_role=workspace_role)
    active_health = broker_health(connect=True)
    if active_health.get("status") != "ready" or active_health.get("connected") is not True:
        return 503, {
            "status": "failed",
            "error": "broker_unavailable",
            "detail": "Browser broker active health check requires the broker token and a reachable Playwright run-server.",
            "broker": active_health,
        }

    steps: list[dict[str, Any]] = []
    session_id = ""
    try:
        create_status, create_result = _smoke_step(
            data_root,
            {"action": "session.create", "mode": mode},
            steps,
            workspace_id=workspace_id,
            app_id=app_id,
            effective_mode=effective_mode,
            platform_role=platform_role,
            workspace_role=workspace_role,
        )
        if create_status >= 400:
            return create_status, _smoke_failed_payload(target_url, active_health, steps, create_result)
        session_id = str(create_result.get("session_id") or "")
        if not session_id:
            return 502, _smoke_failed_payload(
                target_url,
                active_health,
                steps,
                {"error": "invalid_broker_response", "detail": "Browser broker did not return a session_id."},
            )

        for action_body in (
            {"action": "navigate", "session_id": session_id, "url": target_url, "mode": mode},
            {"action": "snapshot", "session_id": session_id},
            {"action": "screenshot", "session_id": session_id, "full_page": False},
            {"action": "console.messages", "session_id": session_id, "limit": 25},
            {"action": "network.requests", "session_id": session_id, "limit": 25},
            {"action": "tabs", "session_id": session_id},
        ):
            step_status, step_result = _smoke_step(
                data_root,
                action_body,
                steps,
                workspace_id=workspace_id,
                app_id=app_id,
                effective_mode=effective_mode,
                platform_role=platform_role,
                workspace_role=workspace_role,
            )
            if step_status >= 400:
                return step_status, _smoke_failed_payload(target_url, active_health, steps, step_result)
    finally:
        if session_id:
            _smoke_step(
                data_root,
                {"action": "session.close", "session_id": session_id},
                steps,
                workspace_id=workspace_id,
                app_id=app_id,
                effective_mode=effective_mode,
                platform_role=platform_role,
                workspace_role=workspace_role,
            )

    if session_id and not _step_ok(steps, "session.close"):
        return 502, _smoke_failed_payload(
            target_url,
            active_health,
            steps,
            {"error": "session_close_failed", "detail": "Browser P0 acceptance smoke could not close the session."},
        )
    return 200, {
        "status": "ok",
        "target_url": redact_url(target_url),
        "broker": active_health,
        "checks": {
            "session_create": _step_ok(steps, "session.create"),
            "navigate": _step_ok(steps, "navigate"),
            "snapshot": _step_ok(steps, "snapshot"),
            "screenshot": _step_ok(steps, "screenshot"),
            "console_messages": _step_ok(steps, "console.messages"),
            "network_requests": _step_ok(steps, "network.requests"),
            "tabs": _step_ok(steps, "tabs"),
            "session_close": _step_ok(steps, "session.close"),
        },
        "steps": steps,
    }


def _smoke_step(
    data_root: Path,
    body: dict[str, Any],
    steps: list[dict[str, Any]],
    *,
    workspace_id: str | None,
    app_id: str,
    effective_mode: str | None,
    platform_role: str | None,
    workspace_role: str | None,
) -> tuple[int, dict[str, Any]]:
    status_code, result = handle_action(
        data_root,
        body,
        app_id=app_id,
        workspace_id=workspace_id,
        effective_mode=effective_mode,
        platform_role=platform_role,
        workspace_role=workspace_role,
    )
    steps.append(_smoke_step_summary(str(body.get("action") or ""), status_code, result))
    return status_code, result


def _smoke_step_summary(action: str, status_code: int, result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"action": action, "status_code": status_code, "ok": status_code < 400}
    for key in ("session_id", "url", "title", "mime_type", "encoding", "error", "detail"):
        if isinstance(result.get(key), str):
            summary[key] = result[key]
    if isinstance(result.get("snapshot"), str):
        summary["snapshot_length"] = len(result["snapshot"])
    if isinstance(result.get("data"), str):
        summary["screenshot_bytes"] = len(result["data"])
    if isinstance(result.get("messages"), list):
        summary["message_count"] = len(result["messages"])
    if isinstance(result.get("requests"), list):
        summary["request_count"] = len(result["requests"])
    if isinstance(result.get("sessions"), list):
        summary["session_count"] = len(result["sessions"])
    return summary


def _smoke_failed_payload(
    target_url: str,
    broker: dict[str, Any],
    steps: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "failed",
        "target_url": redact_url(target_url),
        "broker": broker,
        "error": result.get("error", "acceptance_smoke_failed"),
        "detail": result.get("detail", "Browser P0 acceptance smoke failed."),
        "steps": steps,
    }


def _step_ok(steps: list[dict[str, Any]], action: str) -> bool:
    return any(step.get("action") == action and step.get("ok") is True for step in steps)


def broker_action_result(
    data_root: Path,
    action: str,
    body: dict[str, Any],
    *,
    workspace_id: str | None,
    admin_dev_targets_enabled: bool,
) -> tuple[int, dict[str, Any]]:
    validate_p0_broker_action(action, body)
    session = require_authorized_session(data_root, action, body, admin_dev_targets_enabled=admin_dev_targets_enabled)
    mode = session["mode"] if session is not None else str(body.get("mode") or "read_only")
    if mode == "maverick_dev_inspector" and not admin_dev_targets_enabled:
        raise BrowserPolicyError(
            "Maverick dev inspector sessions require admin authority.",
            decision={"allowed": False, "reason": "blocked_admin_dev_target_not_enabled"},
        )
    allow_admin_dev_targets = mode == "maverick_dev_inspector" and admin_dev_targets_enabled
    if action == "navigate":
        preflight = preflight_payload({**body, "mode": mode}, admin_dev_targets_enabled=admin_dev_targets_enabled)
        if not preflight["allowed"]:
            raise BrowserPolicyError("Navigation target was denied by Browser egress policy.", decision=preflight)
    if action in DEV_INSPECTOR_ACTIONS:
        validate_dev_inspector_action(body, session=session, admin_dev_targets_enabled=admin_dev_targets_enabled)
    if action == "wait_for":
        validate_wait(body)
    response = call_broker_action(
        action,
        broker_payload(
            body,
            workspace_id=workspace_id,
            mode=mode,
            allow_admin_dev_targets=allow_admin_dev_targets,
            admin_dev_targets_enabled=admin_dev_targets_enabled,
        ),
    )
    payload = response.payload
    payload.setdefault("action", action)
    payload.setdefault("broker_provider", "playwright_lab")
    payload.setdefault("mode", mode)
    sync_state_after_broker_action(data_root, action, body, payload, status_code=response.status_code, workspace_id=workspace_id, mode=mode)
    return response.status_code, payload


def validate_p0_broker_action(action: str, body: dict[str, Any]) -> None:
    forbidden = sorted(field for field in FORBIDDEN_PROFILE_FIELDS if field in body)
    if forbidden:
        raise BrowserValidationError(
            "P0 Browser Lab does not allow persistent profiles, storage state, file upload, or automatic download persistence.",
            field=forbidden[0],
        )
    trusted = sorted(field for field in FORBIDDEN_TRUSTED_FIELDS if field in body)
    if trusted:
        raise BrowserValidationError(
            "Browser policy context is derived by the controller and cannot be supplied by callers.",
            field=trusted[0],
        )
    artifact_fields = sorted(field for field in FORBIDDEN_ARTIFACT_FIELDS if field in body)
    if artifact_fields:
        raise BrowserValidationError(
            "Browser P0 does not automatically persist artifacts; Storage handoff requires an explicit future action.",
            field=artifact_fields[0],
        )
    allowed_fields = P0_ACTION_FIELDS.get(action, frozenset({"action"}))
    extra_fields = sorted(field for field in body if field not in allowed_fields)
    if extra_fields:
        raise BrowserValidationError(
            f"{extra_fields[0]} is not allowed for Browser P0 action {action}.",
            field=extra_fields[0],
        )
    if action == "session.create":
        mode = str(body.get("mode") or "read_only")
        if mode not in {"read_only", "maverick_dev_inspector"}:
            raise BrowserValidationError("mode must be read_only or maverick_dev_inspector.", field="mode")
    if action == "navigate" and "mode" in body:
        validate_optional_mode(body)
    if action in SESSION_ACTIONS:
        require_string(body, "session_id")
    if action == "screenshot":
        validate_optional_bool(body, "full_page")
    if action in {"console.messages", "network.requests"}:
        validate_limit(body)
    if action == "wait_for":
        validate_wait(body)
    if action in {"click", "type"}:
        require_string(body, "ref")
    if action == "type":
        require_string(body, "text")
    if action == "press_key":
        require_string(body, "key")


def broker_payload(
    body: dict[str, Any],
    *,
    workspace_id: str | None,
    mode: str,
    allow_admin_dev_targets: bool,
    admin_dev_targets_enabled: bool,
) -> dict[str, Any]:
    payload = {key: value for key, value in body.items() if key != "policy_context"}
    payload.pop("action", None)
    payload["mode"] = mode
    if workspace_id:
        payload["workspace_id"] = workspace_id
    payload["policy_context"] = {"allow_admin_dev_targets": allow_admin_dev_targets}
    payload["caller_context"] = {"admin_dev_targets_enabled": admin_dev_targets_enabled}
    return payload


def preflight_payload(body: dict[str, Any], *, admin_dev_targets_enabled: bool = False) -> dict[str, Any]:
    url = require_string(body, "url")
    mode = str(body.get("mode") or "read_only")
    if mode not in {"read_only", "maverick_dev_inspector"}:
        raise BrowserValidationError("mode must be read_only or maverick_dev_inspector.", field="mode")
    if "resolved_addresses" in body:
        raise BrowserValidationError(
            "resolved_addresses are resolved by trusted Browser policy and cannot be supplied by callers.",
            field="resolved_addresses",
        )
    if "allow_admin_dev_targets" in body:
        raise BrowserValidationError(
            "allow_admin_dev_targets is derived from trusted caller authority and cannot be supplied by callers.",
            field="allow_admin_dev_targets",
        )
    allow_admin_dev_targets = mode == "maverick_dev_inspector" and admin_dev_targets_enabled
    resolved_addresses = resolve_browser_egress_url_addresses(url)
    decision = evaluate_browser_egress_url(
        url,
        resolved_addresses=resolved_addresses,
        allow_admin_dev_targets=allow_admin_dev_targets,
    )
    payload = asdict(decision)
    payload["redacted_url"] = redact_url(url)
    payload["url"] = payload["redacted_url"]
    if payload.get("normalized_url"):
        payload["normalized_url"] = redact_url(str(payload["normalized_url"]))
    return payload


def require_authorized_session(
    data_root: Path,
    action: str,
    body: dict[str, Any],
    *,
    admin_dev_targets_enabled: bool,
) -> dict[str, Any] | None:
    if action not in SESSION_ACTIONS:
        return None
    session_id = require_string(body, "session_id")
    state = load_state(str(data_root))
    session = state["sessions"].get(session_id)
    if not isinstance(session, dict):
        raise BrowserValidationError(f"Unknown Browser session: {session_id}.", field="session_id")
    requested_mode = body.get("mode")
    if isinstance(requested_mode, str) and requested_mode.strip() and requested_mode.strip() != session["mode"]:
        raise BrowserValidationError("mode must match the Browser session mode.", field="mode")
    if session["mode"] == "maverick_dev_inspector" and not admin_dev_targets_enabled:
        raise BrowserPolicyError(
            "Maverick dev inspector session access requires admin authority.",
            decision={"allowed": False, "reason": "blocked_admin_dev_session_not_authorized"},
        )
    return session


def validate_dev_inspector_action(
    body: dict[str, Any],
    *,
    session: dict[str, Any] | None,
    admin_dev_targets_enabled: bool,
) -> None:
    if body.get("mode") != "maverick_dev_inspector":
        raise BrowserPolicyError(
            "Interactive browser actions require mode maverick_dev_inspector.",
            decision={"allowed": False, "reason": "blocked_interactive_action_mode_required"},
        )
    if not session or session["mode"] != "maverick_dev_inspector":
        raise BrowserPolicyError(
            "Interactive browser actions are allowed only in maverick_dev_inspector mode.",
            decision={"allowed": False, "reason": "blocked_interactive_action_outside_dev_inspector"},
        )
    target_url = require_string(body, "target_url")
    decision = preflight_payload(
        {"url": target_url, "mode": "maverick_dev_inspector"},
        admin_dev_targets_enabled=admin_dev_targets_enabled,
    )
    if not decision["allowed"] or decision["reason"] != "allowed_admin_dev_target":
        raise BrowserPolicyError("Interactive browser action target is not an admin-enabled Maverick dev URL.", decision=decision)


def sync_state_after_broker_action(
    data_root: Path,
    action: str,
    body: dict[str, Any],
    payload: dict[str, Any],
    *,
    status_code: int,
    workspace_id: str | None,
    mode: str,
) -> None:
    if status_code >= 400:
        return
    session_id = session_id_from_payload(body, payload)
    if not session_id:
        return
    if action == "session.close":
        remove_session_record(str(data_root), session_id)
        return
    updates = state_updates_for_action(action, body, payload, workspace_id=workspace_id, mode=mode)
    if updates:
        upsert_session_record(str(data_root), session_id, updates)


def state_updates_for_action(
    action: str,
    body: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: str | None,
    mode: str,
) -> dict[str, Any]:
    timestamp = datetime.now(tz=UTC).isoformat()
    updates: dict[str, Any] = {"mode": mode, "updated_at": timestamp}
    if workspace_id:
        updates["workspace_id"] = workspace_id
    if action == "session.create":
        updates.update(
            {
                "created_at": timestamp,
                "provider": str(payload.get("provider") or payload.get("broker_provider") or "playwright_lab"),
                "isolated": bool(payload.get("isolated") is not False),
                "persistent_profile": bool(payload.get("persistent_profile") is True),
                "login_state_persisted": bool(payload.get("login_state_persisted") is True),
                "accept_downloads": bool(payload.get("accept_downloads") is True),
                "file_upload": bool(payload.get("file_upload") is True),
                "url": "about:blank",
                "tabs": [{"url": "about:blank", "active": True}],
            }
        )
    elif action in {"navigate", "snapshot", "screenshot", "wait_for", "click", "type", "press_key"}:
        if isinstance(payload.get("url"), str):
            updates["url"] = redact_url(payload["url"])
        if isinstance(payload.get("title"), str):
            updates["title"] = payload["title"][:500]
    elif action == "console.messages" and isinstance(payload.get("messages"), list):
        updates["console"] = payload["messages"]
    elif action == "network.requests" and isinstance(payload.get("requests"), list):
        updates["network"] = payload["requests"]
    elif action == "tabs":
        updates["tabs"] = tabs_for_session(payload, str(body.get("session_id") or ""))
    return updates


def session_id_from_payload(body: dict[str, Any], payload: dict[str, Any]) -> str:
    value = payload.get("session_id") or body.get("session_id")
    return str(value).strip()[:120] if isinstance(value, str) and value.strip() else ""


def tabs_for_session(payload: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    sessions = payload.get("sessions")
    if isinstance(sessions, list):
        for session in sessions:
            if isinstance(session, dict) and session.get("session_id") == session_id and isinstance(session.get("tabs"), list):
                return [redacted_tab(tab) for tab in session["tabs"] if isinstance(tab, dict)]
    tabs = payload.get("tabs")
    if isinstance(tabs, list):
        return [redacted_tab(tab) for tab in tabs if isinstance(tab, dict)]
    return []


def redacted_tab(tab: dict[str, Any]) -> dict[str, Any]:
    result = {"active": bool(tab.get("active"))}
    if isinstance(tab.get("url"), str):
        result["url"] = redact_url(tab["url"])
    return result


def validate_wait(body: dict[str, Any]) -> None:
    state = body.get("state", "load")
    if not isinstance(state, str) or state not in {"load", "domcontentloaded", "networkidle"}:
        raise BrowserValidationError("state must be load, domcontentloaded, or networkidle.", field="state")
    timeout_ms = body.get("timeout_ms", 5000)
    if type(timeout_ms) is not int or timeout_ms < 0 or timeout_ms > 30000:
        raise BrowserValidationError("timeout_ms must be an integer between 0 and 30000.", field="timeout_ms")


def validate_limit(body: dict[str, Any]) -> None:
    limit = body.get("limit", 100)
    if type(limit) is not int or limit < 1 or limit > 500:
        raise BrowserValidationError("limit must be an integer between 1 and 500.", field="limit")


def validate_optional_bool(body: dict[str, Any], field: str) -> None:
    if field in body and not isinstance(body[field], bool):
        raise BrowserValidationError(f"{field} must be a boolean.", field=field)


def validate_optional_mode(body: dict[str, Any]) -> None:
    mode = body.get("mode")
    if not isinstance(mode, str) or mode not in {"read_only", "maverick_dev_inspector"}:
        raise BrowserValidationError("mode must be read_only or maverick_dev_inspector.", field="mode")


def require_string(body: dict[str, Any], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BrowserValidationError(f"{field} is required.", field=field)
    return value.strip()


def is_admin_authority(*, platform_role: str | None, workspace_role: str | None) -> bool:
    return platform_role == "admin" or workspace_role == "admin"


def audit_browser_action(
    data_root: Path,
    action: str,
    body: dict[str, Any],
    *,
    status: str,
    reason: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    session_id = str(body.get("session_id") or "")[:120]
    audit_mode = mode or str(body.get("mode") or "")
    if session_id and not audit_mode:
        session = load_state(str(data_root))["sessions"].get(session_id)
        if isinstance(session, dict):
            audit_mode = str(session.get("mode") or "")
    record = {
        "action": action,
        "status": status,
        "reason": reason,
        "session_id": session_id,
        "mode": (audit_mode or "read_only")[:80],
    }
    url = body.get("url") or body.get("target_url")
    if isinstance(url, str) and url:
        record["url"] = redact_url(url)
    return append_audit_record(str(data_root), record)


def ensure_installed_state(data_root: Path) -> dict[str, Any]:
    return save_state(str(data_root), load_state(str(data_root)))


def redact_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return "<invalid-url>"
    host = parsed.hostname or ""
    if host and ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if port is not None:
        netloc = f"{netloc}:{port}"
    query = "redacted" if parsed.query else ""
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", query, ""))
