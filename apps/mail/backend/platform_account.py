"""Mail projection of workspace-enabled Core-owned Google accounts."""

import json
from pathlib import Path
from core.app_sdk.account_state import migrate_account_state
from database import connect, ensure_schema, now_timestamp
from platform_account_migration import migrate_state


def attach_platform_account(payload):
    if "external_accounts" not in payload:
        return
    root = Path(payload["data_root"])
    migrate_account_state(payload, migrate_state)
    ensure_schema(root)
    now = now_timestamp()
    projected = set()
    with connect(root) as db:
        for account in payload["external_accounts"]:
            if account.get("provider") != "google":
                continue
            connection_id = "platform_" + account["account_id"]
            projected.add(connection_id)
            ready = "gmail" in account.get("services", []) and bool(account.get("access_handle"))
            existing = db.execute("SELECT settings_json FROM connections WHERE id=?", (connection_id,)).fetchone()
            settings = json.loads(existing[0]) if existing else {}
            settings.update(platform_account_id=account["account_id"], managed_by="platform", is_default=account.get("default", False))
            db.execute("""INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, settings_json, created_at, updated_at)
                VALUES (?, 'gmail', ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET
                email_address=excluded.email_address, display_name=excluded.display_name, status=excluded.status,
                scopes_json=excluded.scopes_json, settings_json=excluded.settings_json, updated_at=excluded.updated_at""",
                (connection_id, account["email"], account["display_name"], "connected" if ready else "disconnected",
                 json.dumps(account.get("scopes", [])), json.dumps(settings), now, now))
            if ready:
                payload.setdefault("app_secrets", {})["platform-google-access:" + connection_id] = account["access_handle"]
        for row in db.execute("SELECT id, settings_json FROM connections").fetchall():
            if row["id"] not in projected and json.loads(row["settings_json"]).get("managed_by") == "platform":
                db.execute("UPDATE connections SET status='disconnected' WHERE id=?", (row["id"],))
