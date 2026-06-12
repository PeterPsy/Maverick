"""Connection setup flows for non-OAuth Mail providers."""

from __future__ import annotations

import json
import re
from pathlib import Path

from database import connect, ensure_schema, now_timestamp
from store import audit, get_connection


IMAP_SMTP_PROVIDER = "imap_smtp"
MAILBOX_PASSWORD_SECRET = "mailbox-password"
IMAP_PASSWORD_SECRET = "imap-password"
SMTP_PASSWORD_SECRET = "smtp-password"
PRIVATE_EMAIL_DEFAULTS = {
    "email_address": "team@loopino.ai",
    "username": "team@loopino.ai",
    "imap_host": "mail.privateemail.com",
    "imap_port": 993,
    "imap_security": "ssl",
    "smtp_host": "mail.privateemail.com",
    "smtp_port": 465,
    "smtp_security": "ssl",
    "sent_folder": "Sent",
}


def prepare_imap_smtp(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    """Create or update an IMAP/SMTP connection without accepting a password."""
    ensure_schema(data_root)
    settings = _settings(payload)
    settings_json = json.dumps(settings, ensure_ascii=True, sort_keys=True)
    workspace_id = _optional_string(payload.get("_workspace_id")) or "default"
    connection_id = _connection_id(settings["email_address"])
    now = now_timestamp()
    with connect(data_root) as db:
        existing = db.execute("SELECT status, settings_json FROM connections WHERE id = ?", (connection_id,)).fetchone()
        status = _prepared_status(existing, settings) if existing is not None else "needs_secret_grant"
        if status not in {"connected", "needs_test", "needs_secret_grant"}:
            status = "needs_secret_grant"
        db.execute(
            """
            INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, settings_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              email_address = excluded.email_address,
              display_name = excluded.display_name,
              status = excluded.status,
              scopes_json = excluded.scopes_json,
              settings_json = excluded.settings_json,
              updated_at = excluded.updated_at
            """,
            (
                connection_id,
                IMAP_SMTP_PROVIDER,
                settings["email_address"],
                settings["display_name"],
                status,
                "[]",
                settings_json,
                now,
                now,
            ),
        )
        _upsert_credential_metadata(db, connection_id, workspace_id, now)
    audit(data_root, "imap_smtp.prepare", "mail_connection", connection_id, {"provider": IMAP_SMTP_PROVIDER})
    return {
        "status": get_connection(data_root, connection_id)["status"],
        "connection_id": connection_id,
        "connection": get_connection(data_root, connection_id),
        "required_secrets": [MAILBOX_PASSWORD_SECRET],
        "resource_scope": {"resource_type": "mail_connection", "resource_id": connection_id},
        "vault": {
            "status": "credentials_required",
            "detail": "Create or grant the mailbox password in Vault/Core Secrets. Mail stores only this redaction-safe resource scope.",
        },
    }


def update_imap_smtp(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    ensure_schema(data_root)
    connection_id = _required_string(payload.get("connection_id"), "connection_id")
    workspace_id = _optional_string(payload.get("_workspace_id")) or "default"
    connection = get_connection(data_root, connection_id)
    if connection.get("provider") != IMAP_SMTP_PROVIDER:
        raise ValueError(f"Connection `{connection_id}` is not an IMAP/SMTP connection")
    current = connection.get("settings") if isinstance(connection.get("settings"), dict) else {}
    settings = _settings({**current, **payload, "email_address": payload.get("email_address") or connection["email_address"]})
    now = now_timestamp()
    next_status = "needs_test" if connection.get("status") != "disconnected" else "needs_secret_grant"
    with connect(data_root) as db:
        db.execute(
            """
            UPDATE connections
            SET email_address = ?, display_name = ?, status = ?, settings_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                settings["email_address"],
                settings["display_name"],
                next_status,
                json.dumps(settings, ensure_ascii=True, sort_keys=True),
                now,
                connection_id,
            ),
        )
        _upsert_credential_metadata(db, connection_id, workspace_id, now)
    audit(data_root, "imap_smtp.update", "mail_connection", connection_id, {"provider": IMAP_SMTP_PROVIDER})
    return {"status": next_status, "connection_id": connection_id, "connection": get_connection(data_root, connection_id)}


def test_imap_smtp(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    from providers.imap_smtp import ImapSmtpProvider

    connection_id = _required_string(payload.get("connection_id"), "connection_id")
    _require_imap_connection(data_root, connection_id)
    previous_status = str(get_connection(data_root, connection_id).get("status") or "")
    result = ImapSmtpProvider().test_connection(data_root, connection_id, app_secrets=_secret_map(payload.get("_app_secrets")))
    status = _tested_status(previous_status, bool(result["ok"]))
    with connect(data_root) as db:
        db.execute("UPDATE connections SET status = ?, updated_at = ? WHERE id = ?", (status, now_timestamp(), connection_id))
    audit(data_root, "imap_smtp.test", "mail_connection", connection_id, {"ok": bool(result["ok"])})
    return {"status": "ready" if result["ok"] else status, "connection_id": connection_id, "test": result, "connection": get_connection(data_root, connection_id)}


def activate_imap_smtp(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    connection_id = _required_string(payload.get("connection_id"), "connection_id")
    tested = test_imap_smtp(data_root, payload)
    if not tested["test"]["ok"]:
        return tested
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute("UPDATE connections SET status = ?, updated_at = ? WHERE id = ?", ("connected", now, connection_id))
        db.execute(
            "UPDATE provider_credentials SET status = ?, updated_at = ? WHERE connection_id = ? AND logical_name = ?",
            ("active", now, connection_id, MAILBOX_PASSWORD_SECRET),
        )
    audit(data_root, "imap_smtp.activate", "mail_connection", connection_id, {"provider": IMAP_SMTP_PROVIDER})
    return {"status": "connected", "connection_id": connection_id, "connection": get_connection(data_root, connection_id)}


def secret_resource_inventory(data_root: Path) -> dict[str, object]:
    """Return redaction-safe resource-scoped secret needs for Core/Vault diagnosis."""
    ensure_schema(data_root)
    with connect(data_root) as db:
        rows = db.execute(
            """
            SELECT provider_credentials.*, connections.email_address, connections.display_name, connections.status AS connection_status
            FROM provider_credentials
            JOIN connections ON connections.id = provider_credentials.connection_id
            WHERE connections.status != 'disconnected'
            ORDER BY connections.updated_at DESC, provider_credentials.logical_name
            """
        ).fetchall()
    resources = []
    for row in rows:
        resource_type = _optional_string(row["resource_type"])
        resource_id = _optional_string(row["resource_id"])
        logical_name = _optional_string(row["logical_name"])
        if not resource_type or not resource_id or not logical_name:
            continue
        resources.append(
            {
                "logical_name": logical_name,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "label": f"{row['display_name'] or row['email_address']} mailbox",
                "status": row["connection_status"],
                "provider": row["provider"],
            }
        )
    return {"resources": resources}


def _upsert_credential_metadata(db, connection_id: str, workspace_id: str, now: str) -> None:
    secret_ref = _scoped_secret_ref(workspace_id, connection_id)
    grant_id = _scoped_grant_id(workspace_id, connection_id)
    db.execute(
        """
        INSERT INTO provider_credentials(
          id, connection_id, provider, logical_name, secret_ref, grant_id,
          resource_type, resource_id, status, metadata_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(connection_id, logical_name) DO UPDATE SET
          secret_ref = excluded.secret_ref,
          grant_id = excluded.grant_id,
          resource_type = excluded.resource_type,
          resource_id = excluded.resource_id,
          updated_at = excluded.updated_at
        """,
        (
            f"provider_credential_{connection_id}_{MAILBOX_PASSWORD_SECRET}",
            connection_id,
            IMAP_SMTP_PROVIDER,
            MAILBOX_PASSWORD_SECRET,
            secret_ref,
            grant_id,
            "mail_connection",
            connection_id,
            "needs_grant",
            json.dumps({"credential_kind": "password", "owner": "vault"}, ensure_ascii=True, sort_keys=True),
            now,
            now,
        ),
    )


def _settings(payload: dict[str, object]) -> dict[str, object]:
    email_address = _required_string(payload.get("email_address") or payload.get("email") or PRIVATE_EMAIL_DEFAULTS["email_address"], "email_address")
    username = _required_string(payload.get("username") or email_address, "username")
    settings = {
        "email_address": email_address,
        "username": username,
        "display_name": _optional_string(payload.get("display_name")) or email_address,
        "imap_host": _required_string(payload.get("imap_host") or PRIVATE_EMAIL_DEFAULTS["imap_host"], "imap_host"),
        "imap_port": _port(payload.get("imap_port"), PRIVATE_EMAIL_DEFAULTS["imap_port"]),
        "imap_security": _security(payload.get("imap_security"), "imap"),
        "smtp_host": _required_string(payload.get("smtp_host") or PRIVATE_EMAIL_DEFAULTS["smtp_host"], "smtp_host"),
        "smtp_port": _port(payload.get("smtp_port"), PRIVATE_EMAIL_DEFAULTS["smtp_port"]),
        "smtp_security": _security(payload.get("smtp_security"), "smtp"),
        "sent_folder": _optional_string(payload.get("sent_folder")) or str(PRIVATE_EMAIL_DEFAULTS["sent_folder"]),
    }
    return settings


def _prepared_status(existing, settings: dict[str, object]) -> str:
    current_status = str(existing["status"] or "")
    if current_status == "disconnected":
        return "needs_secret_grant"
    if current_status == "connected":
        return "connected" if _settings_match(existing["settings_json"], settings) else "needs_test"
    if current_status in {"needs_test", "needs_secret_grant"}:
        return current_status
    return "needs_secret_grant"


def _tested_status(previous_status: str, ok: bool) -> str:
    if not ok:
        return "needs_secret_grant"
    return "connected" if previous_status == "connected" else "needs_test"


def _settings_match(raw_settings: object, next_settings: dict[str, object]) -> bool:
    try:
        current = json.loads(str(raw_settings or "{}"))
    except json.JSONDecodeError:
        current = {}
    return isinstance(current, dict) and current == next_settings


def _require_imap_connection(data_root: Path, connection_id: str) -> None:
    connection = get_connection(data_root, connection_id)
    if connection.get("provider") != IMAP_SMTP_PROVIDER:
        raise ValueError(f"Connection `{connection_id}` is not an IMAP/SMTP connection")


def _connection_id(email_address: str) -> str:
    return f"mail_connection_imap_{_secret_segment(email_address)}"


def _scoped_secret_ref(workspace_id: str, connection_id: str) -> str:
    return f"platform:secret-alias/{_secret_segment(workspace_id)}-mail-{MAILBOX_PASSWORD_SECRET}-mail_connection-{connection_id}"


def _scoped_grant_id(workspace_id: str, connection_id: str) -> str:
    return f"grant:{_secret_segment(workspace_id)}:mail:{MAILBOX_PASSWORD_SECRET}:mail_connection:{connection_id}"


def _secret_segment(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-") or "item"


def _port(value: object, default: object) -> int:
    try:
        parsed = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        raise ValueError("mail server ports must be integers") from None
    if parsed < 1 or parsed > 65535:
        raise ValueError("mail server ports must be between 1 and 65535")
    return parsed


def _security(value: object, protocol: str) -> str:
    text = str(value or "ssl").strip().lower()
    allowed = {"ssl", "starttls", "none"}
    if text not in allowed:
        raise ValueError(f"{protocol}_security must be one of {', '.join(sorted(allowed))}")
    return text


def _required_string(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _optional_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _secret_map(value: object | None) -> dict[str, object]:
    return value if isinstance(value, dict) else {}
