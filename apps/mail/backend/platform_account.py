"""Mail's private mailbox projection of the shared personal Google account."""

import json
from pathlib import Path
from database import connect, ensure_schema, now_timestamp


def attach_platform_account(payload):
    account = next((item for item in payload.get("external_accounts", []) if item.get("provider") == "google"), None)
    if not account:
        return
    root = Path(payload["data_root"])
    ensure_schema(root)
    connection_id = "platform_" + account["account_id"]
    ready = "gmail" in account.get("services", []) and bool(account.get("access_handle"))
    now = now_timestamp()
    with connect(root) as db:
        db.execute("""INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, settings_json, created_at, updated_at)
            VALUES (?, 'gmail', ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET
            email_address=excluded.email_address, display_name=excluded.display_name, status=excluded.status,
            scopes_json=excluded.scopes_json, settings_json=excluded.settings_json, updated_at=excluded.updated_at""",
            (connection_id, account["email"], account["display_name"], "connected" if ready else "disconnected",
             json.dumps(account.get("scopes", [])), json.dumps({"platform_account_id": account["account_id"], "managed_by": "platform"}), now, now))
    if ready:
        payload.setdefault("app_secrets", {})["platform-google-access"] = account["access_handle"]
