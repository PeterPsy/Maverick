"""Calendar projection of workspace-enabled Core-owned Google connections."""

from pathlib import Path
from core.app_sdk.account_state import migrate_account_state
from platform_account_migration import migrate_state
from store import read_state, update_state


def attach_platform_account(payload):
    if "external_accounts" not in payload:
        return
    root = Path(payload["data_root"])
    migrate_account_state(payload, migrate_state)
    projected = {}
    for account in payload["external_accounts"]:
        if account.get("provider") != "google":
            continue
        connection_id = "platform_" + account["account_id"]
        ready = "calendar" in account.get("services", []) and bool(account.get("access_handle"))
        projected[connection_id] = {"id": connection_id, "provider": "google", "account_id": account["email"],
            "account_label": account["display_name"], "status": "connected" if ready else "disabled",
            "scopes": account.get("scopes", []), "external_refs": {"platform_account_id": account["account_id"],
                "managed_by": "platform", "is_default": account.get("default", False)}}
        if ready:
            payload.setdefault("app_secrets", {})["platform-google-access:" + connection_id] = account["access_handle"]

    def update(state):
        connections = {item["id"]: item for item in state["connections"]}
        for item in connections.values():
            if item.get("external_refs", {}).get("managed_by") == "platform" and item["id"] not in projected:
                item["status"] = "disabled"
        for key, item in projected.items():
            existing = connections.get(key, {})
            connections[key] = {**existing, **item,
                "external_refs": {**existing.get("external_refs", {}), **item["external_refs"]}}
        state["connections"] = list(connections.values())
        return state
    current = read_state(root)
    if update(read_state(root)) != current:
        update_state(root, update)
