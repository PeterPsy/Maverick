"""Thin Browser app controller for P0 policy and broker handoff."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from core.egress import evaluate_browser_egress_url

from errors import BrowserBrokerUnavailableError, BrowserPolicyError, BrowserValidationError
from models import AUDITED_ACTIONS, DEV_INSPECTOR_ACTIONS, MCP_TOOL_ACTIONS, READ_ONLY_ACTIONS
from store import append_audit_record, load_state, save_state


ACTION_EVENTS = {"session.create", "session.close"}


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
) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "status").strip()
    try:
        if action in {"status", "operations.manifest"}:
            result = status_payload(data_root, app_id=app_id, workspace_id=workspace_id)
            if action == "operations.manifest":
                result["operations"] = operations_manifest()
            return 200, result
        if action == "policy.preflight":
            return 200, {"policy": preflight_payload(body)}
        if action == "audit.list":
            state = load_state(str(data_root))
            return 200, {"audit": state["audit"], "limit": len(state["audit"])}
        if action in AUDITED_ACTIONS:
            result = broker_action_result(data_root, action, body, workspace_id=workspace_id)
            return 503, result
    except BrowserValidationError as error:
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
) -> tuple[int, dict[str, Any]]:
    action = MCP_TOOL_ACTIONS.get(tool_name)
    if action is None:
        return 400, {
            "error": "unsupported_tool",
            "detail": f"Unsupported Browser MCP tool: {tool_name or '<empty>'}.",
            "allowed_values": {"tool_name": sorted(MCP_TOOL_ACTIONS)},
        }
    return handle_action(data_root, {"action": action, **arguments}, workspace_id=workspace_id, app_id=app_id)


def status_payload(data_root: Path, *, app_id: str, workspace_id: str | None) -> dict[str, Any]:
    state = load_state(str(data_root))
    return {
        "app_id": app_id,
        "workspace_id": workspace_id,
        "schema_version": state["schema_version"],
        "broker": state["broker"],
        "session_count": len(state["sessions"]),
        "audit_count": len(state["audit"]),
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


def broker_action_result(
    data_root: Path,
    action: str,
    body: dict[str, Any],
    *,
    workspace_id: str | None,
) -> dict[str, Any]:
    if action == "navigate":
        preflight = preflight_payload(body)
        if not preflight["allowed"]:
            raise BrowserPolicyError("Navigation target was denied by Browser egress policy.", decision=preflight)
    if action in DEV_INSPECTOR_ACTIONS:
        validate_dev_inspector_action(body)
    if action == "wait_for":
        validate_wait(body)
    raise BrowserBrokerUnavailableError(
        "Browser broker is not connected yet. Passo 4 will attach Playwright run-server and isolated sessions."
    )


def preflight_payload(body: dict[str, Any]) -> dict[str, Any]:
    url = require_string(body, "url")
    resolved_addresses = body.get("resolved_addresses")
    if resolved_addresses is not None:
        if not isinstance(resolved_addresses, list) or not all(isinstance(item, str) for item in resolved_addresses):
            raise BrowserValidationError("resolved_addresses must be a list of IP address strings.", field="resolved_addresses")
    mode = str(body.get("mode") or "read_only")
    allow_admin_dev_targets = mode == "maverick_dev_inspector" or bool(body.get("allow_admin_dev_targets") is True)
    decision = evaluate_browser_egress_url(
        url,
        resolved_addresses=tuple(resolved_addresses) if resolved_addresses is not None else None,
        allow_admin_dev_targets=allow_admin_dev_targets,
    )
    payload = asdict(decision)
    payload["redacted_url"] = redact_url(url)
    return payload


def validate_dev_inspector_action(body: dict[str, Any]) -> None:
    mode = str(body.get("mode") or "")
    if mode != "maverick_dev_inspector":
        raise BrowserPolicyError(
            "Interactive browser actions are allowed only in maverick_dev_inspector mode.",
            decision={"allowed": False, "reason": "blocked_interactive_action_outside_dev_inspector"},
        )
    target_url = require_string(body, "target_url")
    decision = preflight_payload({"url": target_url, "mode": "maverick_dev_inspector"})
    if not decision["allowed"] or decision["reason"] != "allowed_admin_dev_target":
        raise BrowserPolicyError("Interactive browser action target is not an admin-enabled Maverick dev URL.", decision=decision)


def validate_wait(body: dict[str, Any]) -> None:
    timeout_ms = body.get("timeout_ms", 5000)
    if not isinstance(timeout_ms, int) or timeout_ms < 0 or timeout_ms > 30000:
        raise BrowserValidationError("timeout_ms must be an integer between 0 and 30000.", field="timeout_ms")


def require_string(body: dict[str, Any], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BrowserValidationError(f"{field} is required.", field=field)
    return value.strip()


def audit_browser_action(data_root: Path, action: str, body: dict[str, Any], *, status: str, reason: str | None = None) -> dict[str, Any]:
    record = {
        "action": action,
        "status": status,
        "reason": reason,
        "session_id": str(body.get("session_id") or "")[:120],
        "mode": str(body.get("mode") or "read_only")[:80],
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
    except ValueError:
        return "<invalid-url>"
    query = "redacted" if parsed.query else ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", query, ""))
