"""Redaction-safe agent operations for Vault CLI and MCP surfaces."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any


SUPPORTED_OPERATIONS = ["manifest", "diagnose", "connection_issues", "plan_fix", "explain_issue", "apply_fix"]
RAW_VALUE_KEYS = {"raw_value", "secret_value", "credential_value", "plaintext", "password", "token_value"}
CORE_GRANT_CREATE = "core.secret_grants.create"
CORE_RECOMMEND = "core.secret_grant_targets.recommend"

_CORE_ADMIN_STATE: Any | None = None
_CORE_ADMIN_STATE_LOADED = False

CORE_SURFACES = {
    "read_only": [
        {
            "id": "core.secrets.list",
            "authority": "admin read-only; redaction-safe metadata only; raw secret values unavailable",
        },
        {
            "id": "core.secrets.bindings.list",
            "authority": "admin read-only; grant and binding metadata only",
        },
        {
            "id": "core.secret_grant_targets.recommend",
            "authority": "admin read-only; issue-oriented logical needs and recommended grants",
        },
    ],
    "mutative_full_access": [
        {
            "id": CORE_GRANT_CREATE,
            "authority": "full-access admin/operator; validates and creates app secret grants",
        },
        {
            "id": "core.secrets.create",
            "authority": "full-access admin/operator; accepts a raw value for storage but never returns it",
        },
        {
            "id": "core.secrets.rotate",
            "authority": "full-access admin/operator; replaces a raw value but never returns it",
        },
        {
            "id": "core.secrets.update",
            "authority": "full-access admin/operator; updates redaction-safe metadata such as alias, label, description, and kind",
        },
        {
            "id": "core.secrets.disable",
            "authority": "full-access admin/operator; changes delivery eligibility",
        },
        {
            "id": "core.secrets.revoke",
            "authority": "full-access admin/operator; destructive secret lifecycle mutation",
        },
    ],
    "admin_http": [
        {
            "path": "/api/secrets",
            "authority": "platform admin HTTP surface; metadata reads and full-access mutations",
        },
        {
            "path": "/api/secret-grants",
            "authority": "platform admin HTTP surface; grant metadata and grant lifecycle mutations",
        },
        {
            "path": "/api/secret-grant-targets",
            "authority": "platform admin HTTP surface; enabled app logical names eligible for grant creation",
        },
        {
            "path": "/api/secret-grant-needs",
            "authority": "platform admin HTTP surface; redaction-safe issue-oriented grant recommendations",
        },
        {
            "path": "/api/secret-audit",
            "authority": "platform admin HTTP surface; redaction-safe audit reads",
        },
    ],
}


def handle_operation(payload: dict[str, Any], *, action: str) -> dict[str, Any]:
    """Handle one Vault agent operation without exposing raw secret values."""
    arguments = _dict(payload.get("arguments"))
    workspace_id = str(payload.get("workspace_id") or arguments.get("workspace_id") or "").strip() or None
    base = _base_payload(payload, workspace_id=workspace_id, action=action)
    if _contains_raw_value(arguments):
        return {
            **base,
            "status_code": 400,
            "error": "raw_secret_value_rejected",
            "needs_secure_input": True,
            "user_action": "Use the platform-owned Core Secrets secure input flow. Do not send raw secret values through chat, CLI arguments, or MCP payloads.",
        }
    if action == "manifest":
        return {**base, "status_code": 200}
    if action == "diagnose":
        return {**base, "status_code": 200, **_diagnose(arguments, workspace_id=workspace_id)}
    if action == "connection_issues":
        diagnosis = _diagnose(arguments, workspace_id=workspace_id)
        return {
            **base,
            "status_code": 200,
            "issues": diagnosis["issues"],
            "issue_count": diagnosis["issue_count"],
            "payload_kind": "connection_issues",
        }
    if action == "plan_fix":
        return {**base, "status_code": 200, **_plan_fix(arguments, workspace_id=workspace_id)}
    if action == "explain_issue":
        return {**base, "status_code": 200, **_explain_issue(arguments, workspace_id=workspace_id)}
    if action == "apply_fix":
        return {**base, **_apply_fix(arguments, workspace_id=workspace_id)}
    return {
        **base,
        "status_code": 400,
        "error": "unsupported_vault_operation",
        "detail": f"Unsupported Vault operation: {action or '<empty>'}.",
    }


def _base_payload(payload: dict[str, Any], *, workspace_id: str | None, action: str) -> dict[str, Any]:
    return {
        "app_id": payload.get("app_id") or "vault",
        "workspace_id": workspace_id,
        "action": action,
        "redaction_safe": True,
        "secret_values_available": False,
        "core_secret_owner": "core.secrets",
        "core_surfaces": CORE_SURFACES,
        "supported_actions": SUPPORTED_OPERATIONS,
        "supported_operations": SUPPORTED_OPERATIONS,
    }


def _diagnose(arguments: dict[str, Any], *, workspace_id: str | None) -> dict[str, Any]:
    issues = _input_issues(arguments)
    source = "input_issues" if issues else "input_payload"
    if not issues:
        needs = _input_needs(arguments)
        if not needs:
            needs = _load_core_needs(workspace_id)
            source = "core.secret_grant_targets.recommend" if needs else "none"
        issues = [_issue_from_need(need) for need in needs]
        issues = [issue for issue in issues if issue is not None]
    app_id = str(arguments.get("app_id") or "").strip()
    if app_id:
        issues = [issue for issue in issues if issue["app"]["id"] == app_id]
    return {"source": source, "issue_count": len(issues), "issues": issues}


def _input_issues(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    issues = arguments.get("issues")
    if not isinstance(issues, list):
        return []
    return [_sanitize(_dict(issue)) for issue in issues if isinstance(issue, dict) and issue.get("issue_id")]


def _plan_fix(arguments: dict[str, Any], *, workspace_id: str | None) -> dict[str, Any]:
    issue = _select_issue(arguments, workspace_id=workspace_id)
    if issue is None:
        return {"status": "not_found", "steps": [], "mutation_performed": False}
    steps = _steps_for_issue(issue)
    return {"status": "planned", "issue": issue, "steps": steps, "mutation_performed": False}


def _explain_issue(arguments: dict[str, Any], *, workspace_id: str | None) -> dict[str, Any]:
    issue = _select_issue(arguments, workspace_id=workspace_id)
    if issue is None:
        return {
            "status": "not_found",
            "message": "No matching Vault issue was found in the provided redaction-safe payload.",
        }
    return {"status": "explained", "issue_id": issue["issue_id"], "message": _issue_message(issue)}


def _apply_fix(arguments: dict[str, Any], *, workspace_id: str | None) -> dict[str, Any]:
    issue = _select_issue(arguments, workspace_id=workspace_id)
    if issue is None:
        return {"status_code": 404, "status": "not_found", "mutation_performed": False}
    plan = _steps_for_issue(issue)
    if _needs_secure_value(issue):
        return {
            "status_code": 200,
            "status": "needs_secure_input",
            "needs_secure_input": True,
            "user_action": "Add or rotate the secret value through the Core Secrets secure input surface, then rerun diagnose.",
            "issue": issue,
            "steps": plan,
            "mutation_performed": False,
        }
    if not _confirmation_present(arguments):
        return {
            "status_code": 409,
            "status": "confirmation_required",
            "required_confirmation": "confirm_apply_fix",
            "issue": issue,
            "steps": plan,
            "mutation_performed": False,
        }
    create_step = next((step for step in plan if step.get("core_surface") == CORE_GRANT_CREATE), None)
    if create_step is None:
        return {
            "status_code": 200,
            "status": "no_supported_mutation",
            "issue": issue,
            "steps": plan,
            "mutation_performed": False,
        }
    if not _core_cli_surface_available(CORE_GRANT_CREATE):
        return {
            "status_code": 424,
            "status": "core_grant_surface_unavailable",
            "issue": issue,
            "steps": plan,
            "mutation_performed": False,
        }
    result = _call_core_grant_create(create_step["arguments"], workspace_id=workspace_id)
    return {
        "status_code": 200 if result.get("ok") else 502,
        "status": "applied" if result.get("ok") else "core_surface_failed",
        "issue_id": issue["issue_id"],
        "core_surface": CORE_GRANT_CREATE,
        "core_result": _sanitize(result.get("payload", result)),
        "mutation_performed": bool(result.get("ok")),
    }


def _input_needs(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("needs", "items", "issues"):
        value = arguments.get(key)
        if isinstance(value, list):
            return [_dict(item) for item in value if isinstance(item, dict)]
    return []


def _load_core_needs(workspace_id: str | None) -> list[dict[str, Any]]:
    if not workspace_id:
        return []
    state = _core_admin_state()
    if state is None:
        return []
    try:
        from core.api.secret_grant_admin import list_secret_grant_recommendations
    except Exception:
        return []
    try:
        items = list_secret_grant_recommendations(state, workspace_id=workspace_id)
    except Exception:
        return []
    return [_dict(item) for item in items if isinstance(item, dict)]


def _issue_from_need(need: dict[str, Any]) -> dict[str, Any] | None:
    app_id = str(need.get("app_id") or "").strip()
    logical_name = str(need.get("logical_name") or "").strip()
    if not app_id or not logical_name:
        return None
    credential_match = _credential_metadata(_dict(need.get("credential_match")))
    value_state = str(need.get("value_state") or "unknown")
    grant_state = str(need.get("grant_state") or "unknown")
    user_action = str(need.get("user_action") or "review")
    if user_action == "none":
        return None
    scope = _sanitize(_dict(need.get("scope"))) or {"type": "workspace", "label": "Workspace"}
    recommended_grant = _sanitize(_dict(need.get("recommended_grant")))
    issue = {
        "issue_id": _issue_id(app_id=app_id, logical_name=logical_name, scope=scope),
        "severity": _severity(value_state=value_state, grant_state=grant_state, user_action=user_action),
        "app": {"id": app_id, "name": str(need.get("app_name") or app_id)},
        "logical_need": {
            "name": logical_name,
            "label": str(need.get("human_label") or logical_name.replace("-", " ").replace("_", " ").title()),
            "scope": scope,
        },
        "credential_metadata": credential_match,
        "value_state": value_state,
        "grant_state": grant_state,
        "recommended_action": user_action,
        "recommended_grant": recommended_grant,
        "advanced_details": _sanitize(
            {
                "app_managed": bool(need.get("app_managed")),
                "raw_core_need": {
                    "scope": scope,
                    "value_state": value_state,
                    "grant_state": grant_state,
                    "user_action": user_action,
                },
            }
        ),
    }
    return _sanitize(issue)


def _credential_metadata(match: dict[str, Any]) -> dict[str, Any]:
    candidates = match.get("candidates") if isinstance(match.get("candidates"), list) else []
    safe_candidates = []
    for candidate in candidates:
        item = _dict(candidate)
        safe_candidates.append(
            _sanitize(
                {
                    "secret_id": item.get("secret_id"),
                    "alias": item.get("alias"),
                    "label": item.get("label"),
                    "description": item.get("description"),
                    "status": item.get("status"),
                    "kind": item.get("kind"),
                    "match_method": item.get("match_method"),
                    "confidence": item.get("confidence"),
                }
            )
        )
    return {
        "matched": bool(match.get("matched")),
        "method": str(match.get("method") or "none"),
        "confidence": str(match.get("confidence") or "none"),
        "ambiguous": bool(match.get("ambiguous")),
        "candidate_count": int(match.get("candidate_count") or len(safe_candidates)),
        "candidates": safe_candidates,
    }


def _steps_for_issue(issue: dict[str, Any]) -> list[dict[str, Any]]:
    action = str(issue.get("recommended_action") or "")
    if action in {"add_value", "rotate_or_replace_value"}:
        return [
            {
                "step_id": "core.secrets.secure_input",
                "kind": "user_action",
                "needs_secure_input": True,
                "description": "Provide or rotate the secret value through the platform-owned secure input flow.",
            }
        ]
    if action in {"complete_app_setup", "reconnect_app"}:
        return [
            {
                "step_id": "app_managed_secret_setup",
                "kind": "user_action",
                "needs_secure_input": False,
                "description": "Complete the app-owned setup flow so the app can write this secret through platform_secret_writes.",
            }
        ]
    if action == "review_value_match":
        return [
            {
                "step_id": "review_candidate",
                "kind": "user_action",
                "description": "Review the redaction-safe candidate metadata and choose the intended credential before creating a grant.",
            }
        ]
    if action == "create_grant":
        arguments = _grant_arguments_for_issue(issue)
        return [
            {
                "step_id": CORE_GRANT_CREATE,
                "kind": "core_call",
                "core_surface": CORE_GRANT_CREATE,
                "description": "Create the recommended app secret grant through the Core Secrets grant surface.",
                "arguments": arguments,
            }
        ]
    if action == "none":
        return [{"step_id": "no_action", "kind": "none", "description": "No Vault fix is needed for this issue."}]
    return [
        {
            "step_id": "review_grant",
            "kind": "user_action",
            "description": "Review the grant and credential state before making a change.",
        }
    ]


def _grant_arguments_for_issue(issue: dict[str, Any]) -> dict[str, Any]:
    recommended = _dict(issue.get("recommended_grant"))
    credential = _dict(issue.get("credential_metadata"))
    candidates = credential.get("candidates") if isinstance(credential.get("candidates"), list) else []
    first = _dict(candidates[0]) if candidates else {}
    arguments = {
        "app_id": _dict(issue.get("app")).get("id"),
        "logical_name": _dict(issue.get("logical_need")).get("name"),
        "actions": recommended.get("actions") or ["app.backend"],
        "target_patterns": recommended.get("target_patterns") or ["maverick://app.backend/*"],
        "reason": recommended.get("reason") or "Created from Vault agent plan.",
    }
    if first.get("secret_id"):
        arguments["secret_id"] = first["secret_id"]
    elif first.get("alias"):
        arguments["alias"] = first["alias"]
    for key in ("resource_type", "resource_id", "expires_at"):
        if recommended.get(key):
            arguments[key] = recommended[key]
    return _sanitize(arguments)


def _select_issue(arguments: dict[str, Any], *, workspace_id: str | None) -> dict[str, Any] | None:
    diagnosis = _diagnose(arguments, workspace_id=workspace_id)
    issues = diagnosis["issues"]
    issue_id = str(arguments.get("issue_id") or "").strip()
    app_id = str(arguments.get("app_id") or "").strip()
    if issue_id:
        return next((issue for issue in issues if issue["issue_id"] == issue_id), None)
    if app_id:
        return next((issue for issue in issues if issue["app"]["id"] == app_id), None)
    return issues[0] if issues else None


def _issue_message(issue: dict[str, Any]) -> str:
    app = _dict(issue.get("app"))
    need = _dict(issue.get("logical_need"))
    action = str(issue.get("recommended_action") or "review")
    label = str(need.get("label") or need.get("name") or "credential")
    app_name = str(app.get("name") or app.get("id") or "the app")
    if action == "add_value":
        return f"{app_name} needs {label}, but Vault did not find a usable saved credential. Add it through Core Secrets secure input."
    if action == "create_grant":
        return f"{app_name} has a matching saved credential for {label}, but it is not granted to the app yet."
    if action == "review_value_match":
        return f"Vault found possible saved credentials for {label}, but the match is not certain enough to use automatically."
    if action == "rotate_or_replace_value":
        return f"{app_name} is linked to {label}, but the saved credential is disabled or revoked and needs replacement."
    if action == "complete_app_setup":
        return f"{app_name} manages {label}. Complete the app setup flow so the app can store it through Core Secrets."
    if action == "reconnect_app":
        return f"{app_name} manages {label}, but the saved app-managed credential is inactive. Reconnect the app."
    if action == "none":
        return f"{app_name} already has usable access to {label}."
    return f"{app_name} needs review for {label} before Vault can recommend a change."


def _needs_secure_value(issue: dict[str, Any]) -> bool:
    return str(issue.get("recommended_action") or "") in {"add_value", "rotate_or_replace_value"}


def _confirmation_present(arguments: dict[str, Any]) -> bool:
    return arguments.get("confirmation") is True or str(arguments.get("confirmation") or "") == "confirm_apply_fix"


def _core_cli_surface_available(command_id: str) -> bool:
    if command_id not in {
        CORE_RECOMMEND,
        CORE_GRANT_CREATE,
        "core.secrets.list",
        "core.secrets.bindings.list",
        "core.secrets.create",
        "core.secrets.rotate",
        "core.secrets.update",
        "core.secrets.disable",
        "core.secrets.revoke",
    }:
        return False
    return _core_admin_state() is not None


def _call_core_grant_create(arguments: dict[str, Any], *, workspace_id: str | None) -> dict[str, Any]:
    body = {**arguments}
    if workspace_id and not body.get("workspace_id"):
        body["workspace_id"] = workspace_id
    state = _core_admin_state()
    if state is None:
        return {"ok": False, "payload": {"error": "core_state_unavailable"}}
    try:
        from core.api.secret_api_payloads import grant_payload
        from core.api.secret_grant_admin import create_secret_grant_from_payload
    except Exception:
        return {"ok": False, "payload": {"error": "core_grant_surface_unavailable"}}
    try:
        grant, _secret = create_secret_grant_from_payload(
            state,
            workspace_id=str(body.get("workspace_id") or ""),
            payload=body,
            created_by_user_id=None,
        )
    except Exception as error:
        return {
            "ok": False,
            "payload": {
                "error": "core_grant_create_failed",
                "reason": error.__class__.__name__,
            },
        }
    return {
        "ok": True,
        "payload": {
            "command_id": CORE_GRANT_CREATE,
            "created": True,
            "grant": grant_payload(grant, state=state),
        },
    }


def _core_admin_state() -> Any | None:
    global _CORE_ADMIN_STATE, _CORE_ADMIN_STATE_LOADED
    if _CORE_ADMIN_STATE_LOADED:
        return _CORE_ADMIN_STATE
    _CORE_ADMIN_STATE_LOADED = True
    try:
        from core.api.platform_state import bootstrap_platform_state
        from core.shared.repository import installation_paths
    except Exception:
        return None
    try:
        paths = installation_paths(start_path=Path(__file__).resolve())
        _CORE_ADMIN_STATE = bootstrap_platform_state(
            start_path=paths.repository_root,
            bootstrap_admin=False,
        )
    except Exception:
        _CORE_ADMIN_STATE = None
    return _CORE_ADMIN_STATE


def _issue_id(*, app_id: str, logical_name: str, scope: dict[str, Any]) -> str:
    scope_text = json.dumps(scope, sort_keys=True, default=str)
    digest = sha256(f"{app_id}:{logical_name}:{scope_text}".encode("utf-8")).hexdigest()[:12]
    return f"vault-{app_id}-{logical_name}-{digest}"


def _severity(*, value_state: str, grant_state: str, user_action: str) -> str:
    if user_action in {"add_value", "rotate_or_replace_value", "complete_app_setup", "reconnect_app"} or value_state in {"orphaned", "disabled", "revoked"}:
        return "high"
    if user_action in {"create_grant", "review_value_match"} or grant_state in {"missing", "expired", "revoked"}:
        return "medium"
    if user_action == "none":
        return "info"
    return "low"


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items() if str(key).lower() not in RAW_VALUE_KEYS}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _contains_raw_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower() in RAW_VALUE_KEYS or _contains_raw_value(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_raw_value(item) for item in value)
    return False


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
