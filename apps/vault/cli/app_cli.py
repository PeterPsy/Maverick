"""Vault app CLI entrypoint."""

from __future__ import annotations

import json
import sys


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
    ],
    "mutative_full_access": [
        {
            "id": "core.secrets.create",
            "authority": "full-access admin/operator; accepts a raw value for storage but never returns it",
        },
        {
            "id": "core.secrets.rotate",
            "authority": "full-access admin/operator; replaces a raw value but never returns it",
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
            "path": "/api/secret-audit",
            "authority": "platform admin HTTP surface; redaction-safe audit reads",
        },
    ],
}


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    action = str(arguments.get("action") or "manifest")
    result = {
        "status_code": 200,
        "app_id": payload.get("app_id") or "vault",
        "workspace_id": payload.get("workspace_id"),
        "action": action,
        "redaction_safe": True,
        "secret_values_available": False,
        "core_secret_owner": "core.secrets",
        "core_surfaces": CORE_SURFACES,
        "supported_actions": ["manifest"],
    }
    if action != "manifest":
        result["status_code"] = 400
        result["error"] = "unsupported_vault_cli_action"
        result["detail"] = "Vault CLI exposes only a redaction-safe manifest; use core secret surfaces for mutations."
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
