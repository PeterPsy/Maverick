"""Storage's private Drive projection of a Core-owned personal account."""

from pathlib import Path
from drive_connection_store import read_state, replace_connection


def attach_platform_account(payload):
    account = next((item for item in payload.get("external_accounts", []) if item.get("provider") == "google"), None)
    if not account:
        return
    root = Path(payload["data_root"])
    connection_id = "platform_" + account["account_id"]
    ready = "drive" in account.get("services", []) and bool(account.get("access_handle"))
    existing = next((item for item in read_state(root)["connections"] if item["id"] == connection_id), {})
    updated = {**existing, "id": connection_id, "provider": "google_drive", "account_email": account["email"],
        "display_name": account["display_name"], "status": "connected" if ready else "disconnected",
        "access_mode": "full_rw", "scopes": account.get("scopes", []),
        "external_refs": {"platform_account_id": account["account_id"], "google_subject": account["account_id"], "managed_by": "platform"}}
    if any(existing.get(key) != value for key, value in updated.items()):
        replace_connection(root, updated)
    if ready:
        payload.setdefault("app_secrets", {})["platform-google-access"] = account["access_handle"]
