"""Calendar projection of the Core-owned personal Google connection."""

from pathlib import Path
from store import read_state, update_state


def attach_platform_account(payload):
    accounts = payload.get("external_accounts", [])
    account = next((item for item in accounts if item.get("provider") == "google"), None)
    if not account:
        return
    root = Path(payload["data_root"])
    connection_id = "platform_" + account["account_id"]
    status = "connected" if "calendar" in account.get("services", []) and account.get("access_handle") else "disabled"
    connection = {"id": connection_id, "provider": "google", "account_id": account["email"],
        "account_label": account["display_name"], "status": status, "scopes": account.get("scopes", []),
        "external_refs": {"platform_account_id": account["account_id"], "managed_by": "platform"}}
    state = read_state(root)
    existing = next((item for item in state["connections"] if item["id"] == connection_id), None)
    if existing is None or any(existing.get(key) != value for key, value in connection.items()):
        def update(current):
            current["connections"] = [item for item in current["connections"] if item["id"] != connection_id]
            current["connections"].append({**(existing or {}), **connection})
            return current
        update_state(root, update)
    if account.get("access_handle") and "calendar" in account.get("services", []):
        payload.setdefault("app_secrets", {})["platform-google-access"] = account["access_handle"]
