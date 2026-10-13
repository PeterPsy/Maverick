"""Storage projection of workspace-enabled Core-owned Google accounts."""

from pathlib import Path
from core.app_sdk.account_state import migrate_account_state
from drive_connection_store import read_state, update_state
from platform_account_migration import migrate_state, migrate_workspace_account


def attach_platform_account(payload):
    if "external_accounts" not in payload:
        return
    root = Path(payload["data_root"])
    migrate_account_state(payload, migrate_state)
    for account in payload["external_accounts"]:
        if account.get("provider") == "google" and "drive" in account.get("services", []):
            migrate_account_state(payload, migrate_state,
                migrate_workspace=lambda source, target: migrate_workspace_account(source, target, account),
                workspace_migration_id="storage-drive:" + account["account_id"])
    projected = {}
    for account in payload["external_accounts"]:
        if account.get("provider") != "google":
            continue
        connection_id = "platform_" + account["account_id"]
        ready = "drive" in account.get("services", []) and bool(account.get("access_handle"))
        projected[connection_id] = {"id": connection_id, "provider": "google_drive", "account_email": account["email"],
            "display_name": account["display_name"], "picture_url": account.get("picture_url", ""),
            "status": "connected" if ready else "disconnected",
            "access_mode": "full_rw", "scopes": account.get("scopes", []),
            "external_refs": {"platform_account_id": account["account_id"], "google_subject": account["account_id"],
                "managed_by": "platform", "is_default": account.get("default", False)}}
        if ready:
            payload.setdefault("app_secrets", {})["platform-google-access:" + connection_id] = account["access_handle"]

    def update(state):
        connections = {item["id"]: item for item in state["connections"]}
        for item in connections.values():
            if item.get("external_refs", {}).get("managed_by") == "platform" and item["id"] not in projected:
                item["status"] = "disconnected"
        for key, item in projected.items():
            existing = connections.get(key, {})
            connections[key] = {**existing, **item,
                "external_refs": {**existing.get("external_refs", {}), **item["external_refs"]}}
        state["connections"] = list(connections.values())
        return state
    current = read_state(root)
    if update(read_state(root)) != current:
        update_state(root, update)
