"""Mail app service tests."""

from __future__ import annotations

import base64
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

APP_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = APP_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))
from backend.service import handle_action, resolve_secret_resource, resolve_secret_resource_inventory
from backend.service import app_events_for_action
from backend.database import connect, ensure_schema, health_payload, now_timestamp
from backend.providers.gmail import GmailProvider
from backend.providers.imap_smtp import ImapSmtpProvider
from backend.storage_attachments import save_attachment_to_storage
from backend.store import list_threads


class MailServiceTest(unittest.TestCase):
    def test_mounted_backend_entrypoint_resolves_core_from_app_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = {
                "app_id": "mail",
                "workspace_id": "default",
                "data_root": tmp,
                "body": {"action": "health.check"},
                "app_secrets": {},
                "generated_storage_root": "",
            }
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)

            result = subprocess.run(
                [sys.executable, str(APP_ROOT / "backend" / "app_backend.py")],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                cwd=str(APP_ROOT.parents[1]),
                env=env,
                timeout=10,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            response = json.loads(result.stdout)
            self.assertEqual(response["status_code"], 200)
            self.assertEqual(response["json"]["health_status"], "healthy")

    def test_fresh_install_has_no_demo_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "threads.list", "mailbox": "inbox"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["items"], [])
            status, payload = handle_action(Path(tmp), {"action": "connections.list"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["items"], [])

    def test_prepare_imap_smtp_stores_only_metadata_and_vault_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, payload = handle_action(data_root, {"action": "connections.prepare_imap_smtp"})

            self.assertEqual(status, 201)
            self.assertEqual(payload["connection_id"], "mail_connection_imap_team-loopino.ai")
            self.assertEqual(payload["status"], "needs_secret_grant")
            self.assertEqual(payload["required_secrets"], ["mailbox-password"])
            self.assertEqual(payload["resource_scope"], {"resource_type": "mail_connection", "resource_id": "mail_connection_imap_team-loopino.ai"})
            self.assertNotIn("raw-secret", json.dumps(payload))
            with connect(data_root) as db:
                connection = db.execute("SELECT * FROM connections WHERE id = ?", ("mail_connection_imap_team-loopino.ai",)).fetchone()
                credential = db.execute("SELECT * FROM provider_credentials WHERE connection_id = ?", ("mail_connection_imap_team-loopino.ai",)).fetchone()
            self.assertEqual(connection["provider"], "imap_smtp")
            self.assertEqual(connection["email_address"], "team@loopino.ai")
            settings = json.loads(connection["settings_json"])
            self.assertEqual(settings["imap_host"], "mail.privateemail.com")
            self.assertEqual(settings["smtp_port"], 465)
            self.assertEqual(credential["logical_name"], "mailbox-password")
            self.assertEqual(credential["resource_type"], "mail_connection")
            self.assertEqual(credential["resource_id"], "mail_connection_imap_team-loopino.ai")
            inventory = resolve_secret_resource_inventory(data_root)
            self.assertEqual(
                inventory["resources"],
                [
                    {
                        "logical_name": "mailbox-password",
                        "resource_type": "mail_connection",
                        "resource_id": "mail_connection_imap_team-loopino.ai",
                        "label": "team@loopino.ai mailbox",
                        "status": "needs_secret_grant",
                        "provider": "imap_smtp",
                    }
                ],
            )

    def test_prepare_imap_smtp_is_idempotent_for_connected_unchanged_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, payload = handle_action(data_root, {"action": "connections.prepare_imap_smtp"})
            self.assertEqual(status, 201)
            connection_id = payload["connection_id"]
            with connect(data_root) as db:
                db.execute("UPDATE connections SET status = ? WHERE id = ?", ("connected", connection_id))

            status, payload = handle_action(data_root, {"action": "connections.prepare_imap_smtp"})
            self.assertEqual(status, 201)
            self.assertEqual(payload["connection"]["status"], "connected")

            status, payload = handle_action(data_root, {"action": "connections.prepare_imap_smtp", "smtp_port": 587})
            self.assertEqual(status, 201)
            self.assertEqual(payload["connection"]["status"], "needs_test")

    def test_secret_resource_lookup_distinguishes_gmail_and_imap_smtp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, settings_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", "{}", now, now),
                )
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, settings_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "mail_connection_imap_team-loopino.ai",
                        "imap_smtp",
                        "team@loopino.ai",
                        "team@loopino.ai",
                        "connected",
                        "[]",
                        json.dumps({"email_address": "team@loopino.ai", "username": "team@loopino.ai"}),
                        now,
                        now,
                    ),
                )

            self.assertFalse(
                resolve_secret_resource(
                    data_root,
                    {
                        "connection_id": "mail_connection_gmail_person-example.com",
                        "_app_secret_selector": {"logical_names": ["mailbox-password"]},
                    },
                )["requires_secrets"]
            )
            self.assertFalse(
                resolve_secret_resource(
                    data_root,
                    {
                        "connection_id": "mail_connection_imap_team-loopino.ai",
                        "_app_secret_selector": {"logical_names": ["gmail-refresh-token"]},
                    },
                )["requires_secrets"]
            )
            imap_lookup = resolve_secret_resource(
                data_root,
                {
                    "connection_id": "mail_connection_imap_team-loopino.ai",
                    "_app_secret_selector": {"logical_names": ["mailbox-password"]},
                },
            )
            self.assertTrue(imap_lookup["requires_secrets"])
            self.assertEqual(imap_lookup["resource_id"], "mail_connection_imap_team-loopino.ai")

    def test_threads_sync_uses_bounded_interactive_default(self) -> None:
        class FakeProvider:
            provider_id = "gmail"

            def __init__(self) -> None:
                self.max_threads: int | None = None

            def sync_incremental(
                self,
                data_root: Path,
                connection_id: str | None = None,
                app_secrets: dict[str, object] | None = None,
                max_threads: int = 100,
                query: str | None = None,
                page_token: str | None = None,
                continue_cursor: bool = False,
            ) -> dict[str, object]:
                self.max_threads = max_threads
                return {"connection_id": connection_id, "synced_threads": 0, "has_more": False}

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            connection_id = "mail_connection_gmail_person-example.com"
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (connection_id, "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )

            provider = FakeProvider()
            with patch("backend.service.provider_for_connection", return_value=provider):
                status, payload = handle_action(
                    data_root,
                    {"action": "threads.sync", "connection_id": connection_id, "_app_secrets": self._gmail_secrets()},
                )

            self.assertEqual(status, 200)
            self.assertEqual(payload["sync"]["synced_threads"], 0)
            self.assertEqual(provider.max_threads, 25)

    def test_secret_resource_lookup_remaps_disconnected_connection_to_active_same_mailbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_old", "gmail", "person@example.com", "Person", "disconnected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_new", "gmail", "person@example.com", "Person", "connected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_thread_gmail_mail_connection_gmail_old_thread_1", "mail_connection_gmail_old", "thread-1", "Subject", "[]", now, "", 0, 0, "[]", now),
                )

            result = resolve_secret_resource(data_root, {"action": "mail_get_thread", "thread_id": "email_thread_gmail_mail_connection_gmail_old_thread_1"})

            self.assertTrue(result["requires_secrets"])
            self.assertEqual(result["resource_type"], "mail_connection")
            self.assertEqual(result["resource_id"], "mail_connection_gmail_new")

    def test_threads_sync_remaps_disconnected_explicit_connection_to_active_same_mailbox(self) -> None:
        class FakeProvider:
            provider_id = "gmail"

            def __init__(self) -> None:
                self.connection_id: str | None = None

            def sync_incremental(
                self,
                data_root: Path,
                connection_id: str | None = None,
                app_secrets: dict[str, object] | None = None,
                max_threads: int = 100,
                query: str | None = None,
                page_token: str | None = None,
                continue_cursor: bool = False,
            ) -> dict[str, object]:
                self.connection_id = connection_id
                return {"connection_id": connection_id, "synced_threads": 0, "has_more": False}

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_old", "gmail", "person@example.com", "Person", "disconnected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_new", "gmail", "person@example.com", "Person", "connected", "[]", now, now),
                )

            provider = FakeProvider()
            with patch("backend.service.provider_for_connection", return_value=provider):
                status, payload = handle_action(
                    data_root,
                    {"action": "threads.sync", "connection_id": "mail_connection_gmail_old", "_app_secrets": self._gmail_secrets()},
                )

            self.assertEqual(status, 200)
            self.assertEqual(provider.connection_id, "mail_connection_gmail_new")
            self.assertEqual(payload["sync"]["connection_id"], "mail_connection_gmail_new")

    def test_imap_smtp_sync_and_send_use_delivered_mailbox_secret(self) -> None:
        source = EmailMessage()
        source["From"] = "Sender <sender@example.com>"
        source["To"] = "Loopino <team@loopino.ai>"
        source["Subject"] = "Private mailbox thread"
        source["Date"] = "Sat, 30 May 2026 12:00:00 +0000"
        source["Message-ID"] = "<private-1@example.com>"
        source.set_content("Hello from private mail")
        raw_message = source.as_bytes()
        sent_messages: list[EmailMessage] = []
        logins: list[tuple[str, str]] = []

        class FakeImap:
            def login(self, username: str, password: str):
                logins.append((username, password))
                return "OK", [b"logged in"]

            def list(self):
                return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

            def select(self, folder: str, readonly: bool = True):
                return "OK", [b"1"]

            def response(self, code: str):
                return "OK", [b"42"]

            def uid(self, command: str, *args):
                if command == "SEARCH":
                    return "OK", [b"1"]
                if command == "FETCH":
                    return "OK", [(b"1 (RFC822)", raw_message)]
                if command == "STORE":
                    return "OK", [b"stored"]
                raise AssertionError(command)

            def append(self, folder: str, flags: str, date_time: object, message: bytes):
                return "OK", [b"appended"]

            def logout(self):
                return "OK", [b"bye"]

        class FakeSmtp:
            def login(self, username: str, password: str):
                logins.append((username, password))
                return (235, b"ok")

            def send_message(self, message: EmailMessage):
                sent_messages.append(message)
                return {}

            def quit(self):
                return (221, b"bye")

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, prepared = handle_action(data_root, {"action": "connections.prepare_imap_smtp"})
            self.assertEqual(status, 201)
            provider = ImapSmtpProvider(imap_factory=lambda settings: FakeImap(), smtp_factory=lambda settings: FakeSmtp())
            with patch("providers.imap_smtp.ImapSmtpProvider", return_value=provider):
                status, tested = handle_action(
                    data_root,
                    {
                        "action": "connections.test_imap_smtp",
                        "connection_id": prepared["connection_id"],
                        "_app_secrets": {"mailbox-password": "mailbox-secret"},
                    },
                )
            self.assertEqual(status, 200, tested)
            self.assertEqual(tested["status"], "ready")
            with patch("backend.service.provider_for_connection", return_value=provider):
                status, synced = handle_action(
                    data_root,
                    {
                        "action": "threads.sync",
                        "connection_id": prepared["connection_id"],
                        "_app_secrets": {"mailbox-password": "mailbox-secret"},
                    },
                )
            self.assertEqual(status, 400)
            self.assertIn("test and activate", synced["detail"])
            with patch("providers.imap_smtp.ImapSmtpProvider", return_value=provider):
                status, activated = handle_action(
                    data_root,
                    {
                        "action": "connections.activate_imap_smtp",
                        "connection_id": prepared["connection_id"],
                        "_app_secrets": {"mailbox-password": "mailbox-secret"},
                    },
                )
            self.assertEqual(status, 200, activated)
            self.assertEqual(activated["status"], "connected")
            with patch("providers.imap_smtp.ImapSmtpProvider", return_value=provider):
                status, retested = handle_action(
                    data_root,
                    {
                        "action": "connections.test_imap_smtp",
                        "connection_id": prepared["connection_id"],
                        "_app_secrets": {"mailbox-password": "mailbox-secret"},
                    },
                )
            self.assertEqual(status, 200, retested)
            self.assertEqual(retested["status"], "ready")
            self.assertEqual(retested["connection"]["status"], "connected")
            with patch("backend.service.provider_for_connection", return_value=provider):
                status, synced = handle_action(
                    data_root,
                    {
                        "action": "threads.sync",
                        "connection_id": prepared["connection_id"],
                        "_app_secrets": {"mailbox-password": "mailbox-secret"},
                    },
                )
            self.assertEqual(status, 200, synced)
            self.assertEqual(synced["sync"]["mode"], "imap_smtp")
            threads = list_threads(data_root, {"connection_id": prepared["connection_id"]})
            self.assertEqual(len(threads), 1)
            self.assertEqual(threads[0]["subject"], "Private mailbox thread")

            status, draft_payload = handle_action(
                data_root,
                {
                    "action": "drafts.create",
                    "connection_id": prepared["connection_id"],
                    "to": [{"email": "customer@example.com"}],
                    "subject": "SMTP send",
                    "body_text": "Plain",
                    "body_html": "<p>HTML</p>",
                },
            )
            self.assertEqual(status, 201)
            with patch("backend.service.provider_for_connection", return_value=provider):
                status, sent = handle_action(
                    data_root,
                    {
                        "action": "drafts.send",
                        "draft_id": draft_payload["draft"]["id"],
                        "confirm": True,
                        "_app_secrets": {"mailbox-password": "mailbox-secret"},
                    },
                )
            self.assertEqual(status, 200, sent)
            self.assertTrue(sent["result"]["sent"])
            self.assertEqual(sent_messages[0]["From"], "team@loopino.ai")
            self.assertIn(("team@loopino.ai", "mailbox-secret"), logins)

    def test_imap_smtp_incremental_sync_uses_uid_search_key(self) -> None:
        messages: dict[int, bytes] = {}
        for uid, subject in ((1, "First cached"), (2, "New after cursor")):
            message = EmailMessage()
            message["From"] = "Sender <sender@example.com>"
            message["To"] = "Loopino <team@loopino.ai>"
            message["Subject"] = subject
            message["Date"] = f"Tue, 02 Jun 2026 14:{uid:02d}:00 +0000"
            message["Message-ID"] = f"<private-{uid}@example.com>"
            message.set_content(subject)
            messages[uid] = message.as_bytes()
        search_calls: list[tuple[object, ...]] = []

        class FakeImap:
            def login(self, username: str, password: str):
                return "OK", [b"logged in"]

            def list(self):
                return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

            def select(self, folder: str, readonly: bool = True):
                return "OK", [b"2"]

            def response(self, code: str):
                return "OK", [b"42"]

            def uid(self, command: str, *args):
                if command == "SEARCH":
                    search_calls.append(args)
                    if args == (None, "ALL"):
                        return "OK", [b"1"]
                    if args == (None, "UID", "2:*"):
                        return "OK", [b"2"]
                    return "OK", [b""]
                if command == "FETCH":
                    uid = int(args[0])
                    return "OK", [(f"{uid} (RFC822)".encode("ascii"), messages[uid])]
                raise AssertionError(command)

            def logout(self):
                return "OK", [b"bye"]

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            connection_id = "mail_connection_imap_team-loopino.ai"
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, settings_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        connection_id,
                        "imap_smtp",
                        "team@loopino.ai",
                        "team@loopino.ai",
                        "connected",
                        "[]",
                        json.dumps({"username": "team@loopino.ai", "email_address": "team@loopino.ai"}),
                        now,
                        now,
                    ),
                )

            provider = ImapSmtpProvider(imap_factory=lambda settings: FakeImap())
            provider.sync_incremental(data_root, connection_id, app_secrets={"mailbox-password": "mailbox-secret"})
            result = provider.sync_incremental(
                data_root,
                connection_id,
                app_secrets={"mailbox-password": "mailbox-secret"},
                continue_cursor=True,
            )

            self.assertEqual(search_calls[-1], (None, "UID", "2:*"))
            self.assertEqual(result["synced_messages"], 1)
            threads = list_threads(data_root, {"connection_id": connection_id, "query": "New after cursor"})
            self.assertEqual(len(threads), 1)

    def test_mock_bootstrap_action_is_not_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "connections.bootstrap_mock"})
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "unsupported_action")

    def test_schema_migration_removes_legacy_mock_provider_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_demo", "mock", "mock@example.com", "Mock Mailbox", "mock_connected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_thread_demo_welcome", "mail_connection_demo", "demo-thread", "Mock", "[]", now, "", 0, 0, "[]", now),
                )
                db.execute(
                    """
                    INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, headers_json, has_attachments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_message_demo_welcome", "email_thread_demo_welcome", "demo-message", "{}", "[]", now, "Mock body", "{}", 0),
                )
                db.execute(
                    """
                    INSERT INTO drafts(id, connection_id, thread_id, to_json, cc_json, bcc_json, subject, body_text, status, dirty, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_draft_demo", "mail_connection_demo", "email_thread_demo_welcome", "[]", "[]", "[]", "Mock draft", "Body", "draft", 1, now, now),
                )

            status, connections = handle_action(data_root, {"action": "connections.list"})
            self.assertEqual(status, 200)
            self.assertEqual(connections["items"], [])
            self.assertNotIn("mock", {item["provider"] for item in connections["providers"]})
            with connect(data_root) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM messages").fetchone()["count"], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM drafts").fetchone()["count"], 0)

    def test_disconnect_gmail_marks_credential_without_deleting_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO oauth_credentials(id, connection_id, provider, secret_ref, grant_id, encrypted_token_json, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "oauth_credential_mail_connection_gmail_person-example.com",
                        "mail_connection_gmail_person-example.com",
                        "gmail",
                        "platform:secret-alias/default-mail-gmail-refresh-token-mail_connection-mail_connection_gmail_person-example.com",
                        "grant:default:mail:gmail-refresh-token:mail_connection:mail_connection_gmail_person-example.com",
                        "{}",
                        "active",
                        now,
                        now,
                    ),
                )
                db.execute(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_thread_gmail_thread_1", "mail_connection_gmail_person-example.com", "thread-1", "Subject", "[]", now, "", 0, 0, "[]", now),
                )
                db.execute(
                    """
                    INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, headers_json, has_attachments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_message_gmail_msg_1", "email_thread_gmail_thread_1", "msg-1", "{}", "[]", now, "Historic body", "{}", 0),
                )

            status, payload = handle_action(
                data_root,
                {
                    "action": "connections.disconnect",
                    "connection_id": "mail_connection_gmail_person-example.com",
                },
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["disconnect"]["connection"]["status"], "disconnected")
            self.assertEqual(payload["disconnect"]["oauth_credentials_disconnected"], 1)
            self.assertEqual(payload["disconnect"]["cache"], {"thread_count": 1, "message_count": 1, "attachment_count": 0, "draft_count": 0})
            with connect(data_root) as db:
                connection = db.execute("SELECT status FROM connections WHERE id = ?", ("mail_connection_gmail_person-example.com",)).fetchone()
                credential = db.execute("SELECT status, secret_ref, grant_id FROM oauth_credentials").fetchone()
                thread_count = db.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"]
                message_count = db.execute("SELECT COUNT(*) AS count FROM messages").fetchone()["count"]
            self.assertEqual(connection["status"], "disconnected")
            self.assertEqual(credential["status"], "disconnected")
            self.assertTrue(credential["secret_ref"])
            self.assertTrue(credential["grant_id"])
            self.assertEqual(thread_count, 1)
            self.assertEqual(message_count, 1)
            secret_lookup = resolve_secret_resource(data_root, {"action": "mail_sync", "connection_id": "mail_connection_gmail_person-example.com"})
            self.assertFalse(secret_lookup["requires_secrets"])
            self.assertEqual(secret_lookup["status"], "disconnected")
            status, sync_payload = handle_action(data_root, {"action": "mail_sync", "connection_id": "mail_connection_gmail_person-example.com"})
            self.assertEqual(status, 400)
            self.assertIn("disconnected", sync_payload["detail"])
            status, send_payload = handle_action(
                data_root,
                {
                    "action": "mail_send",
                    "connection_id": "mail_connection_gmail_person-example.com",
                    "to": [{"email": "recipient@example.com"}],
                    "subject": "Blocked",
                    "body_text": "Disconnected connections must not send.",
                    "confirm": True,
                    "_app_secrets": {
                        "gmail-oauth-client-id": "client-id",
                        "gmail-oauth-client-secret": "client-secret",
                        "gmail-refresh-token": "refresh-token",
                    },
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("disconnected", send_payload["detail"])
            with connect(data_root) as db:
                draft_count = db.execute("SELECT COUNT(*) AS count FROM drafts").fetchone()["count"]
            self.assertEqual(draft_count, 0)

    def test_disconnect_missing_connection_returns_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "connections.disconnect", "connection_id": "missing"})

            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "validation_error")
            self.assertIn("Connection `missing` was not found", payload["detail"])

    def test_delete_disconnected_connection_purges_local_mail_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            connection_id = "mail_connection_gmail_person-example.com"
            thread_id = "email_thread_gmail_thread_1"
            message_id = "email_message_gmail_msg_1"
            attachment_id = "mail_attachment_gmail_att_1"
            draft_id = "mail_draft_person_1"
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (connection_id, "gmail", "person@example.com", "person@example.com", "disconnected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO oauth_credentials(id, connection_id, provider, secret_ref, grant_id, encrypted_token_json, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("oauth_credential_person", connection_id, "gmail", "platform:secret-alias/person", "grant:person", "{}", "disconnected", now, now),
                )
                db.execute(
                    """
                    INSERT INTO provider_credentials(id, connection_id, provider, logical_name, secret_ref, grant_id, resource_type, resource_id, status, metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("provider_credential_person", connection_id, "gmail", "gmail-refresh-token", "platform:secret-alias/person", "grant:person", "mail_connection", connection_id, "disconnected", "{}", now, now),
                )
                db.execute(
                    "INSERT INTO folders(id, connection_id, provider_folder_id, name, canonical, folder_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("folder_person_inbox", connection_id, "INBOX", "Inbox", "inbox", "inbox", now, now),
                )
                db.execute(
                    "INSERT INTO labels(id, connection_id, provider_label_id, name, canonical) VALUES (?, ?, ?, ?, ?)",
                    ("label_person_inbox", connection_id, "INBOX", "Inbox", "inbox"),
                )
                db.execute(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (thread_id, connection_id, "thread-1", "Subject", "[]", now, "Snippet", 1, 0, '["inbox"]', now),
                )
                db.execute(
                    """
                    INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, headers_json, has_attachments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (message_id, thread_id, "msg-1", "{}", "[]", now, "Body", "{}", 1),
                )
                db.execute(
                    """
                    INSERT INTO attachments(id, message_id, provider_attachment_id, filename, content_type, size_bytes, storage_state, storage_ref_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (attachment_id, message_id, "att-1", "report.pdf", "application/pdf", 10, "metadata_only", "{}", now, now),
                )
                db.execute(
                    """
                    INSERT INTO drafts(id, connection_id, thread_id, to_json, cc_json, bcc_json, subject, body_text, status, dirty, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (draft_id, connection_id, thread_id, "[]", "[]", "[]", "Draft", "Draft body", "draft", 1, now, now),
                )
                db.execute(
                    """
                    INSERT INTO sync_state(connection_id, last_sync_at, last_error, cursor, last_full_sync_at, last_incremental_sync_at, provider_history_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (connection_id, now, "", "{}", now, now, "history-1"),
                )
                db.executemany(
                    """
                    INSERT INTO entity_links(id, source_entity_type, source_entity_id, target_app_id, target_entity_type, target_entity_id, relation, metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ("link_connection", "mail_connection", connection_id, "memory", "memory_node", "memory-1", "mentions", "{}", now, now),
                        ("link_thread", "email_thread", thread_id, "memory", "memory_node", "memory-2", "mentions", "{}", now, now),
                        ("link_message", "email_message", message_id, "memory", "memory_node", "memory-3", "mentions", "{}", now, now),
                    ],
                )

            status, payload = handle_action(data_root, {"action": "connections.delete", "connection_id": connection_id})

            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["delete"]["status"], "deleted")
            self.assertEqual(payload["delete"]["cache"], {"thread_count": 1, "message_count": 1, "attachment_count": 1, "draft_count": 1})
            self.assertEqual(payload["delete"]["deleted"]["connection_count"], 1)
            self.assertEqual(payload["delete"]["deleted"]["thread_count"], 1)
            self.assertEqual(payload["delete"]["deleted"]["message_count"], 1)
            self.assertEqual(payload["delete"]["deleted"]["attachment_count"], 1)
            self.assertEqual(payload["delete"]["deleted"]["draft_count"], 1)
            self.assertEqual(payload["delete"]["deleted"]["folder_count"], 1)
            self.assertEqual(payload["delete"]["deleted"]["label_count"], 1)
            self.assertEqual(payload["delete"]["deleted"]["sync_state_count"], 1)
            self.assertEqual(payload["delete"]["deleted"]["oauth_credential_count"], 1)
            self.assertEqual(payload["delete"]["deleted"]["provider_credential_count"], 1)
            self.assertEqual(payload["delete"]["deleted"]["entity_link_count"], 3)
            with connect(data_root) as db:
                for table in [
                    "connections",
                    "oauth_credentials",
                    "provider_credentials",
                    "folders",
                    "labels",
                    "threads",
                    "messages",
                    "attachments",
                    "drafts",
                    "sync_state",
                    "entity_links",
                ]:
                    with self.subTest(table=table):
                        self.assertEqual(db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"], 0)
                audit_row = db.execute("SELECT action, target_id FROM audit_log WHERE action = ?", ("connections.delete",)).fetchone()
            self.assertEqual(audit_row["target_id"], connection_id)

    def test_delete_connected_connection_requires_disconnect_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            connection_id = "mail_connection_gmail_person-example.com"
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (connection_id, "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )

            status, payload = handle_action(data_root, {"action": "connections.delete", "connection_id": connection_id})

            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "validation_error")
            self.assertIn("must be disconnected before removal", payload["detail"])
            with connect(data_root) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM connections").fetchone()["count"], 1)

    def test_threads_list_returns_pagination_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            self._insert_gmail_fixture(data_root)
            status, first_page = handle_action(data_root, {"action": "threads.list", "mailbox": "inbox", "max_threads": 1, "offset": 0})
            self.assertEqual(status, 200)
            self.assertEqual(first_page["limit"], 1)
            self.assertEqual(first_page["offset"], 0)
            self.assertGreaterEqual(first_page["total_count"], 1)
            self.assertLessEqual(len(first_page["items"]), 1)
            status, second_page = handle_action(data_root, {"action": "threads.list", "mailbox": "inbox", "max_threads": 1, "offset": 1})
            self.assertEqual(status, 200)
            self.assertEqual(second_page["limit"], 1)
            self.assertEqual(second_page["offset"], 1)
            self.assertEqual(second_page["total_count"], first_page["total_count"])

    def test_mailbox_counts_are_scoped_by_connection_and_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            connection_id = self._insert_gmail_fixture(data_root)

            status, payload = handle_action(data_root, {"action": "mailboxes.counts"})

            self.assertEqual(status, 200)
            counts = payload["counts"][connection_id]
            self.assertGreaterEqual(counts["inbox"]["total"], 1)
            self.assertGreaterEqual(counts["inbox"]["unread"], 1)
            self.assertGreaterEqual(counts["starred"]["total"], 1)
            self.assertEqual(counts["sent"]["total"], 0)

    def test_threads_list_counts_implicit_gmail_default_connection_filter(self) -> None:
        class FakeGmailProvider:
            provider_id = "gmail"

            def __init__(self) -> None:
                self.payload: dict[str, object] = {}

            def list_threads(self, data_root: Path, payload: dict[str, object]) -> list[dict[str, object]]:
                self.payload = payload
                return list_threads(data_root, payload)

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            with connect(data_root) as db:
                db.executemany(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, 'gmail', ?, ?, 'connected', '[]', ?, ?)
                    """,
                    [
                        (
                            "mail_connection_gmail_a-example.com",
                            "a@example.com",
                            "a@example.com",
                            "2026-01-02T00:00:00+00:00",
                            "2026-01-02T00:00:00+00:00",
                        ),
                        (
                            "mail_connection_gmail_b-example.com",
                            "b@example.com",
                            "b@example.com",
                            "2026-01-01T00:00:00+00:00",
                            "2026-01-01T00:00:00+00:00",
                        ),
                    ],
                )
                db.executemany(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, '[]', ?, '', 0, 0, '["inbox"]', ?)
                    """,
                    [
                        ("email_thread_gmail_a_1", "mail_connection_gmail_a-example.com", "thread-a", "A", "2026-01-02T00:00:00+00:00", "2026-01-02T00:00:00+00:00"),
                        ("email_thread_gmail_b_1", "mail_connection_gmail_b-example.com", "thread-b", "B", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
                    ],
                )

            provider = FakeGmailProvider()
            with patch("backend.service.provider_for_connection", return_value=provider):
                status, payload = handle_action(
                    data_root,
                    {
                        "action": "threads.list",
                        "mailbox": "inbox",
                        "_app_secrets": {"gmail-refresh-token": "refresh-token"},
                    },
                )

            self.assertEqual(status, 200)
            self.assertEqual(provider.payload["connection_id"], "mail_connection_gmail_a-example.com")
            self.assertEqual([item["connection_id"] for item in payload["items"]], ["mail_connection_gmail_a-example.com"])
            self.assertEqual(payload["total_count"], 1)

    def test_threads_list_filters_multiple_mailbox_scopes_as_union(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            with connect(data_root) as db:
                db.executemany(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, 'gmail', ?, ?, 'connected', '[]', ?, ?)
                    """,
                    [
                        ("mail_connection_gmail_a-example.com", "a@example.com", "a@example.com", "2026-01-02T00:00:00+00:00", "2026-01-02T00:00:00+00:00"),
                        ("mail_connection_gmail_b-example.com", "b@example.com", "b@example.com", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
                    ],
                )
                db.executemany(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, '[]', ?, '', 0, 0, ?, ?)
                    """,
                    [
                        (
                            "email_thread_gmail_a_inbox",
                            "mail_connection_gmail_a-example.com",
                            "thread-a-inbox",
                            "A inbox",
                            "2026-01-04T00:00:00+00:00",
                            '["inbox"]',
                            "2026-01-04T00:00:00+00:00",
                        ),
                        (
                            "email_thread_gmail_a_sent",
                            "mail_connection_gmail_a-example.com",
                            "thread-a-sent",
                            "A sent",
                            "2026-01-03T00:00:00+00:00",
                            '["sent"]',
                            "2026-01-03T00:00:00+00:00",
                        ),
                        (
                            "email_thread_gmail_b_inbox",
                            "mail_connection_gmail_b-example.com",
                            "thread-b-inbox",
                            "B inbox",
                            "2026-01-02T00:00:00+00:00",
                            '["inbox"]',
                            "2026-01-02T00:00:00+00:00",
                        ),
                        (
                            "email_thread_gmail_b_trash",
                            "mail_connection_gmail_b-example.com",
                            "thread-b-trash",
                            "B trash",
                            "2026-01-01T00:00:00+00:00",
                            '["trash"]',
                            "2026-01-01T00:00:00+00:00",
                        ),
                    ],
                )

            status, payload = handle_action(
                data_root,
                {
                    "action": "threads.list",
                    "mailbox": "trash",
                    "connection_id": "mail_connection_gmail_b-example.com",
                    "mailbox_scopes": "all:inbox,connection:mail_connection_gmail_a-example.com:sent",
                },
            )

            self.assertEqual(status, 200)
            self.assertEqual({item["subject"] for item in payload["items"]}, {"A inbox", "A sent", "B inbox"})
            self.assertEqual(payload["total_count"], 3)

            status, empty_payload = handle_action(
                data_root,
                {"action": "threads.list", "mailbox": "inbox", "mailbox_scopes": ""},
            )
            self.assertEqual(status, 200)
            self.assertEqual(empty_payload["items"], [])
            self.assertEqual(empty_payload["total_count"], 0)

    def test_legacy_demo_connection_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_demo", "gmail", "demo@example.com", "Demo Mailbox", "mock_connected", "[]", now, now),
                )
            status, payload = handle_action(data_root, {"action": "connections.list"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["items"], [])

    def test_get_thread_returns_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            self._insert_gmail_fixture(data_root)
            _, listed = handle_action(data_root, {"action": "threads.list"})
            thread_id = listed["items"][0]["id"]
            status, payload = handle_action(data_root, {"action": "threads.get", "thread_id": thread_id})
            self.assertEqual(status, 200)
            self.assertEqual(payload["thread"]["id"], thread_id)
            self.assertGreaterEqual(len(payload["thread"]["messages"]), 1)

    def test_message_search_returns_attachment_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            self._insert_gmail_fixture(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO attachments(id, message_id, provider_attachment_id, filename, content_type, size_bytes, storage_state, storage_ref_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "mail_attachment_fixture_ops_roadmap",
                        "email_message_gmail_fixture_ops_1",
                        "provider-attachment-roadmap",
                        "roadmap.pdf",
                        "application/pdf",
                        2048,
                        "metadata_only",
                        "{}",
                        now,
                        now,
                    ),
                )

            status, payload = handle_action(data_root, {"action": "messages.search", "query": "roadmap.pdf"})

            self.assertEqual(status, 200)
            self.assertEqual(payload["items"][0]["attachments"][0]["filename"], "roadmap.pdf")
            self.assertEqual(payload["items"][0]["attachments"][0]["size_bytes"], 2048)

    def test_create_and_preview_send_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            self._insert_gmail_fixture(data_root)
            status, created = handle_action(
                data_root,
                {
                    "action": "drafts.create",
                    "to": [{"email": "customer@example.com"}],
                    "subject": "Follow up",
                    "body_text": "Thanks for the context.",
                },
            )
            self.assertEqual(status, 201)
            draft_id = created["draft"]["id"]
            status, preview = handle_action(data_root, {"action": "drafts.send", "draft_id": draft_id})
            self.assertEqual(status, 200)
            self.assertTrue(preview["result"]["dry_run"])
            self.assertTrue(preview["result"]["requires_confirmation"])
            self.assertEqual(preview["result"]["draft"]["body_html"], "")
            self.assertEqual(preview["result"]["draft"]["reply_to"], [])

    def test_gmail_draft_preview_validates_workspace_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            data_root = workspace_root / "data" / "mail"
            generated_root = workspace_root / "storage" / "generated"
            attachment_path = generated_root / "reports" / "result.txt"
            attachment_path.parent.mkdir(parents=True)
            attachment_path.write_text("storage attachment", encoding="utf-8")
            self._insert_gmail_fixture(data_root)
            status, created = handle_action(
                data_root,
                {
                    "action": "drafts.create",
                    "to": [{"email": "customer@example.com"}],
                    "subject": "Follow up",
                    "body_text": "See attached.",
                    "workspace_attachments": ["storage/generated/reports/result.txt"],
                    "_generated_storage_root": str(generated_root),
                },
            )
            self.assertEqual(status, 201, created)
            attachment_path.unlink()

            status, preview = handle_action(
                data_root,
                {
                    "action": "drafts.send",
                    "draft_id": created["draft"]["id"],
                    "_generated_storage_root": str(generated_root),
                },
            )

            self.assertEqual(status, 400)
            self.assertIn("was not found", preview["detail"])

    def test_gmail_draft_preview_returns_current_attachment_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            data_root = workspace_root / "data" / "mail"
            generated_root = workspace_root / "storage" / "generated"
            attachment_path = generated_root / "reports" / "result.txt"
            attachment_path.parent.mkdir(parents=True)
            attachment_path.write_text("old attachment", encoding="utf-8")
            self._insert_gmail_fixture(data_root)
            status, created = handle_action(
                data_root,
                {
                    "action": "drafts.create",
                    "to": [{"email": "customer@example.com"}],
                    "subject": "Follow up",
                    "body_text": "See attached.",
                    "workspace_attachments": ["storage/generated/reports/result.txt"],
                    "_generated_storage_root": str(generated_root),
                },
            )
            self.assertEqual(status, 201, created)
            attachment_path.write_text("fresh attachment", encoding="utf-8")

            status, preview = handle_action(
                data_root,
                {
                    "action": "drafts.send",
                    "draft_id": created["draft"]["id"],
                    "_generated_storage_root": str(generated_root),
                },
            )

            expected_sha = hashlib.sha256(b"fresh attachment").hexdigest()
            self.assertEqual(status, 200, preview)
            self.assertEqual(preview["result"]["confirmation_preview"]["attachments"][0]["sha256"], expected_sha)
            self.assertRegex(preview["result"]["confirmation_preview"]["confirmation_token"], r"^[0-9a-f]{64}$")
            self.assertEqual(preview["result"]["draft"]["workspace_attachments"][0]["sha256"], expected_sha)
            self.assertEqual(preview["result"]["confirmation_preview"]["attachments"][0]["size_bytes"], len("fresh attachment"))

    def test_gmail_draft_confirm_with_workspace_attachment_requires_confirmation_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            data_root = workspace_root / "data" / "mail"
            generated_root = workspace_root / "storage" / "generated"
            attachment_path = generated_root / "reports" / "result.txt"
            attachment_path.parent.mkdir(parents=True)
            attachment_path.write_text("storage attachment", encoding="utf-8")
            self._insert_gmail_fixture(data_root)
            status, created = handle_action(
                data_root,
                {
                    "action": "drafts.create",
                    "to": [{"email": "customer@example.com"}],
                    "subject": "Follow up",
                    "body_text": "See attached.",
                    "workspace_attachments": ["storage/generated/reports/result.txt"],
                    "_generated_storage_root": str(generated_root),
                },
            )
            self.assertEqual(status, 201, created)

            status, payload = handle_action(
                data_root,
                {
                    "action": "drafts.send",
                    "draft_id": created["draft"]["id"],
                    "confirm": True,
                    "_generated_storage_root": str(generated_root),
                },
            )

            self.assertEqual(status, 400)
            self.assertIn("confirmation_token", payload["detail"])

    def test_gmail_draft_confirm_rejects_changed_workspace_attachment_snapshot(self) -> None:
        transport_calls: list[str] = []

        def fake_transport(request) -> dict[str, object]:
            transport_calls.append(request.full_url)
            raise AssertionError(f"unexpected request {request.full_url}")

        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            data_root = workspace_root / "data" / "mail"
            generated_root = workspace_root / "storage" / "generated"
            uploaded_root = workspace_root / "storage" / "uploaded"
            attachment_path = generated_root / "reports" / "result.txt"
            attachment_path.parent.mkdir(parents=True)
            attachment_path.write_text("preview attachment", encoding="utf-8")
            self._insert_gmail_fixture(data_root)
            status, created = handle_action(
                data_root,
                {
                    "action": "drafts.create",
                    "to": [{"email": "customer@example.com"}],
                    "subject": "Follow up",
                    "body_text": "See attached.",
                    "workspace_attachments": ["storage/generated/reports/result.txt"],
                    "_generated_storage_root": str(generated_root),
                },
            )
            self.assertEqual(status, 201, created)
            status, preview = handle_action(
                data_root,
                {
                    "action": "drafts.send",
                    "draft_id": created["draft"]["id"],
                    "_generated_storage_root": str(generated_root),
                    "_uploaded_storage_root": str(uploaded_root),
                },
            )
            self.assertEqual(status, 200, preview)
            confirmation_token = preview["result"]["confirmation_preview"]["confirmation_token"]
            attachment_path.write_text("changed attachment", encoding="utf-8")

            with patch("backend.service.provider_for_connection", return_value=GmailProvider(transport=fake_transport)):
                status, payload = handle_action(
                    data_root,
                    {
                        "action": "drafts.send",
                        "draft_id": created["draft"]["id"],
                        "confirm": True,
                        "confirmation_token": confirmation_token,
                        "_app_secrets": self._gmail_secrets(),
                        "_generated_storage_root": str(generated_root),
                        "_uploaded_storage_root": str(uploaded_root),
                    },
                )

            self.assertEqual(status, 400)
            self.assertIn("snapshot changed", payload["detail"])
            self.assertEqual(transport_calls, [])

    def test_mail_send_accepts_html_body_and_sends_multipart_gmail_message(self) -> None:
        sent_payloads: list[dict[str, object]] = []

        def fake_transport(request) -> dict[str, object]:
            if request.full_url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token", "expires_in": 3600, "token_type": "Bearer"}
            if request.full_url == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send":
                payload = json.loads(request.data.decode("utf-8"))
                sent_payloads.append(payload)
                return {"id": "provider-message-html", "threadId": ""}
            raise AssertionError(f"unexpected request {request.full_url}")

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            self._insert_gmail_fixture(data_root)
            with patch("backend.service.provider_for_connection", return_value=GmailProvider(transport=fake_transport)):
                status, payload = handle_action(
                    data_root,
                    {
                        "action": "mail_send",
                        "to": [{"email": "customer@example.com", "name": "Customer"}],
                        "subject": "Richiesta ricevuta | Loopino",
                        "body_text": "Plain confirmation",
                        "body_html": "<p><strong>HTML confirmation</strong></p>",
                        "reply_to": [{"email": "team@loopino.ai", "name": "Loopino"}],
                        "confirm": True,
                        "_app_secrets": self._gmail_secrets(),
                    },
                )

            self.assertEqual(status, 200, payload)
            self.assertTrue(payload["result"]["sent"])
            self.assertEqual(payload["draft"]["body_html"], "<p><strong>HTML confirmation</strong></p>")
            self.assertEqual(payload["draft"]["reply_to"][0]["email"], "team@loopino.ai")
            self.assertEqual(len(sent_payloads), 1)
            raw = str(sent_payloads[0]["raw"])
            padded = raw + ("=" * (-len(raw) % 4))
            message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(padded.encode("ascii")))
            self.assertEqual(message["Reply-To"], "Loopino <team@loopino.ai>")
            self.assertEqual(message.get_body(preferencelist=("plain",)).get_content().strip(), "Plain confirmation")
            self.assertEqual(message.get_body(preferencelist=("html",)).get_content().strip(), "<p><strong>HTML confirmation</strong></p>")

    def test_mail_send_attaches_workspace_storage_file(self) -> None:
        sent_payloads: list[dict[str, object]] = []

        def fake_transport(request) -> dict[str, object]:
            if request.full_url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token", "expires_in": 3600, "token_type": "Bearer"}
            if request.full_url == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send":
                payload = json.loads(request.data.decode("utf-8"))
                sent_payloads.append(payload)
                return {"id": "provider-message-attachment", "threadId": ""}
            raise AssertionError(f"unexpected request {request.full_url}")

        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            data_root = workspace_root / "data" / "mail"
            generated_root = workspace_root / "storage" / "generated"
            uploaded_root = workspace_root / "storage" / "uploaded"
            attachment_path = generated_root / "reports" / "result.txt"
            attachment_path.parent.mkdir(parents=True)
            attachment_path.write_text("storage attachment", encoding="utf-8")
            self._insert_gmail_fixture(data_root)

            with patch("backend.service.provider_for_connection", return_value=GmailProvider(transport=fake_transport)):
                status, preview = handle_action(
                    data_root,
                    {
                        "action": "mail_send",
                        "to": [{"email": "customer@example.com"}],
                        "subject": "Attachment",
                        "body_text": "See attached.",
                        "workspace_attachments": ["storage/generated/reports/result.txt"],
                        "_generated_storage_root": str(generated_root),
                        "_uploaded_storage_root": str(uploaded_root),
                    },
                )
                self.assertEqual(status, 200, preview)
                confirmation_token = preview["result"]["confirmation_preview"]["confirmation_token"]
                status, payload = handle_action(
                    data_root,
                    {
                        "action": "mail_send",
                        "to": [{"email": "customer@example.com"}],
                        "subject": "Attachment",
                        "body_text": "See attached.",
                        "workspace_attachments": ["storage/generated/reports/result.txt"],
                        "confirm": True,
                        "confirmation_token": confirmation_token,
                        "_app_secrets": self._gmail_secrets(),
                        "_generated_storage_root": str(generated_root),
                        "_uploaded_storage_root": str(uploaded_root),
                    },
                )

            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["draft"]["workspace_attachments"][0]["workspace_relative_path"], "storage/generated/reports/result.txt")
            raw = str(sent_payloads[0]["raw"])
            padded = raw + ("=" * (-len(raw) % 4))
            message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(padded.encode("ascii")))
            attachments = list(message.iter_attachments())
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get_filename(), "result.txt")
            self.assertEqual(attachments[0].get_payload(decode=True), b"storage attachment")

    def test_save_thread_attachments_dedupes_and_targets_storage_folder(self) -> None:
        calls: list[dict[str, object]] = []
        content = b"same-content"
        data_base64url = base64.urlsafe_b64encode(content).decode("ascii").rstrip("=")

        class FakeProvider:
            def fetch_attachment(self, data_root: Path, attachment_id: str, **kwargs) -> dict[str, object]:
                calls.append({"attachment_id": attachment_id, **kwargs})
                sha256 = hashlib.sha256(content).hexdigest()
                if sha256 in kwargs.get("skip_sha256s", set()):
                    return {"status": "duplicate_sha256", "size_bytes": len(content), "sha256": sha256}
                if kwargs.get("save_to_storage"):
                    storage_ref = save_attachment_to_storage(
                        data_root,
                        attachment_id=attachment_id,
                        filename="report.pdf",
                        content_type="application/pdf",
                        attachment_bytes=content,
                        generated_storage_root=kwargs.get("generated_storage_root"),
                        target_folder=kwargs.get("storage_target_folder"),
                        mode=kwargs.get("storage_mode"),
                    )
                    return {"status": "saved", "size_bytes": len(content), "sha256": sha256, "storage_ref": storage_ref}
                return {
                    "status": "fetched",
                    "size_bytes": len(content),
                    "data_base64url": data_base64url,
                }

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_thread_gmail_thread_1", "mail_connection_gmail_person-example.com", "thread-1", "Subject", "[]", now, "", 0, 0, "[]", now),
                )
                db.execute(
                    """
                    INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, headers_json, has_attachments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_message_gmail_msg_1", "email_thread_gmail_thread_1", "msg-1", "{}", "[]", now, "", "{}", 1),
                )
                for attachment_id in ("att_1", "att_2"):
                    db.execute(
                        """
                        INSERT INTO attachments(id, message_id, provider_attachment_id, filename, content_type, size_bytes, storage_state, storage_ref_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (attachment_id, "email_message_gmail_msg_1", attachment_id, "report.pdf", "application/pdf", len(content), "metadata_only", "{}", now, now),
                    )

            with patch("backend.service.provider_for_connection", return_value=FakeProvider()):
                status, payload = handle_action(
                    data_root,
                    {
                        "action": "mail_save_attachments",
                        "thread_id": "email_thread_gmail_thread_1",
                        "target_folder": "storage/generated/customer",
                        "_generated_storage_root": str(Path(tmp) / "storage" / "generated"),
                    },
                )

            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["saved_count"], 1)
            self.assertEqual(payload["skipped"][0]["reason"], "duplicate_sha256")
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(call["save_to_storage"] is True for call in calls))
            self.assertNotIn("data_base64url", calls[0])
            saved_files = sorted((Path(tmp) / "storage" / "generated" / "customer").iterdir())
            self.assertEqual([item.name for item in saved_files], ["report.pdf"])

    def test_save_thread_attachments_does_not_skip_same_metadata_with_different_hashes(self) -> None:
        calls: list[str] = []
        contents = {
            "att_1": b"first-bytes!",
            "att_2": b"other-bytes!",
        }

        class FakeProvider:
            def fetch_attachment(self, data_root: Path, attachment_id: str, **kwargs) -> dict[str, object]:
                calls.append(attachment_id)
                key = "att_1" if attachment_id.endswith("att_1") else "att_2"
                content = contents[key]
                sha256 = hashlib.sha256(content).hexdigest()
                if kwargs.get("save_to_storage"):
                    storage_ref = save_attachment_to_storage(
                        data_root,
                        attachment_id=attachment_id,
                        filename="report.pdf",
                        content_type="application/pdf",
                        attachment_bytes=content,
                        generated_storage_root=kwargs.get("generated_storage_root"),
                        target_folder=kwargs.get("storage_target_folder"),
                        mode=kwargs.get("storage_mode"),
                    )
                    return {"status": "saved", "size_bytes": len(content), "sha256": sha256, "storage_ref": storage_ref}
                return {
                    "status": "fetched",
                    "size_bytes": len(content),
                    "data_base64url": base64.urlsafe_b64encode(content).decode("ascii").rstrip("="),
                }

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_thread_gmail_thread_1", "mail_connection_gmail_person-example.com", "thread-1", "Subject", "[]", now, "", 0, 0, "[]", now),
                )
                db.execute(
                    """
                    INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, headers_json, has_attachments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_message_gmail_msg_1", "email_thread_gmail_thread_1", "msg-1", "{}", "[]", now, "", "{}", 1),
                )
                for attachment_id in ("att_1", "att_2"):
                    db.execute(
                        """
                        INSERT INTO attachments(id, message_id, provider_attachment_id, filename, content_type, size_bytes, storage_state, storage_ref_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (attachment_id, "email_message_gmail_msg_1", attachment_id, "report.pdf", "application/pdf", 12, "metadata_only", "{}", now, now),
                    )

            with patch("backend.service.provider_for_connection", return_value=FakeProvider()):
                status, payload = handle_action(
                    data_root,
                    {
                        "action": "mail_save_attachments",
                        "thread_id": "email_thread_gmail_thread_1",
                        "target_folder": "storage/generated/customer",
                        "_generated_storage_root": str(Path(tmp) / "storage" / "generated"),
                    },
                )

            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["saved_count"], 2)
            self.assertEqual(payload["skipped_count"], 0)
            self.assertEqual([call.rsplit("_", 1)[-1] for call in calls], ["1", "2"])
            saved_files = sorted((Path(tmp) / "storage" / "generated" / "customer").iterdir())
            self.assertEqual([item.name for item in saved_files], ["report.pdf", "report.v2.pdf"])

    def test_mail_send_confirm_requires_recipient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            self._insert_gmail_fixture(data_root)
            status, payload = handle_action(
                data_root,
                {
                    "action": "mail_send",
                    "subject": "No recipient",
                    "body_text": "This must not be sent.",
                    "confirm": True,
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("recipient", payload["detail"])

    def test_send_draft_without_recipient_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            connection_id = self._insert_gmail_fixture(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO drafts(id, connection_id, to_json, cc_json, bcc_json, subject, body_text, status, dirty, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_draft_missing_recipients", connection_id, "[]", "[]", "[]", "No recipient", "Blocked.", "draft", 1, now, now),
                )
            status, payload = handle_action(data_root, {"action": "drafts.send", "draft_id": "mail_draft_missing_recipients", "confirm": True})
            self.assertEqual(status, 400)
            self.assertIn("recipient", payload["detail"])

    def test_reply_draft_derives_recipient_from_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            self._insert_gmail_fixture(data_root)
            _, listed = handle_action(data_root, {"action": "threads.list"})
            thread_id = listed["items"][0]["id"]
            status, payload = handle_action(
                data_root,
                {
                    "action": "drafts.create",
                    "thread_id": thread_id,
                    "subject": "Re: Welcome",
                    "body_text": "Thanks.",
                },
            )
            self.assertEqual(status, 201)
            self.assertTrue(payload["draft"]["to"][0]["email"])
            self.assertNotEqual(payload["draft"]["to"][0]["email"], "person@example.com")

    def test_mcp_draft_action_emits_data_event(self) -> None:
        events = app_events_for_action("mail_create_draft")
        self.assertEqual(events, [{"type": "maverick.app.data-changed", "owner_app_id": "mail", "resource": "drafts"}])

    def test_disconnect_action_emits_connection_event(self) -> None:
        events = app_events_for_action("connections.disconnect")
        self.assertEqual(events, [{"type": "maverick.app.data-changed", "owner_app_id": "mail", "resource": "connections"}])

    def test_attachment_get_emits_thread_event_only_after_storage_save(self) -> None:
        for action in ("attachments.get", "mail_get_attachment"):
            with self.subTest(action=action):
                saved_events = app_events_for_action(action, {"fetch": {"status": "saved"}})
                self.assertEqual(saved_events, [{"type": "maverick.app.data-changed", "owner_app_id": "mail", "resource": "threads"}])

        for result in (
            None,
            {},
            {"fetch": {"status": "metadata_only"}},
            {"fetch": {"status": "fetched"}},
            {"fetch": {"status": "too_large"}},
        ):
            with self.subTest(result=result):
                self.assertEqual(app_events_for_action("attachments.get", result), [])

    def test_schema_includes_provider_and_link_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "health.check"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["schema_version"], "8")
            self.assertEqual(payload["health_status"], "healthy")
            self.assertEqual(payload["database"], "mail.sqlite")
            with connect(Path(tmp)) as db:
                message_columns = {row["name"] for row in db.execute("PRAGMA table_info(messages)").fetchall()}
                draft_columns = {row["name"] for row in db.execute("PRAGMA table_info(drafts)").fetchall()}
                connection_columns = {row["name"] for row in db.execute("PRAGMA table_info(connections)").fetchall()}
                provider_credential_table = db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'provider_credentials'").fetchone()
            self.assertIn("body_html_original_bounded", message_columns)
            self.assertIn("body_html_gmail_sanitized", message_columns)
            self.assertIn("body_html_rendered", message_columns)
            self.assertIn("workspace_attachments_json", draft_columns)
            self.assertIn("render_policy_json", message_columns)
            self.assertIn("body_html", draft_columns)
            self.assertIn("reply_to_json", draft_columns)
            self.assertIn("settings_json", connection_columns)
            self.assertIsNotNone(provider_credential_table)

    def test_read_only_health_reports_missing_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = health_payload(Path(tmp), initialize=False)
            self.assertEqual(payload["health_status"], "missing_database")

    def test_oauth_start_requires_secret_grant_without_leaking_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "connections.start_oauth", "provider": "gmail"})
            self.assertEqual(status, 409)
            self.assertEqual(payload["status"], "not_configured")
            self.assertIn("gmail-oauth-client-id", payload["required_secrets"])
            self.assertNotIn("token", str(payload).lower())

    def test_oauth_rejects_unowned_redirect_uri(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(
                Path(tmp),
                {
                    "action": "connections.start_oauth",
                    "provider": "gmail",
                    "redirect_uri": "https://example.com/callback",
                    "_app_secrets": {"gmail-oauth-client-id": "client-id"},
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("/apps/mail/oauth/callback", payload["detail"])

    def test_oauth_accepts_legacy_root_shell_redirect_uri(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(
                Path(tmp),
                {
                    "action": "connections.start_oauth",
                    "provider": "gmail",
                    "redirect_uri": "https://maverick.local/app/mail/oauth/callback",
                    "_app_secrets": {"gmail-oauth-client-id": "client-id"},
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["callback_path"], "/apps/mail/oauth/callback")

    def test_oauth_missing_client_secret_does_not_consume_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, started = handle_action(
                data_root,
                {
                    "action": "connections.start_oauth",
                    "provider": "gmail",
                    "redirect_uri": "https://maverick.local/apps/mail/oauth/callback",
                    "_app_secrets": {"gmail-oauth-client-id": "client-id"},
                },
            )
            self.assertEqual(status, 200)
            for _ in range(2):
                status, completed = handle_action(
                    data_root,
                    {"action": "connections.complete_oauth", "state": started["state"], "code": "code"},
                )
                self.assertEqual(status, 409)
                self.assertEqual(completed["status"], "needs_secret_grant")

    def test_oauth_complete_stores_refresh_token_reference_only(self) -> None:
        class FakeGmailProvider:
            def fetch_profile(self, *, access_token: str) -> dict[str, object]:
                assert access_token == "access-token"
                return {"emailAddress": "person@example.com"}

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, started = handle_action(
                data_root,
                {
                    "action": "connections.start_oauth",
                    "provider": "gmail",
                    "redirect_uri": "https://maverick.local/apps/mail/oauth/callback",
                    "_app_secrets": {"gmail-oauth-client-id": "client-id"},
                },
            )
            self.assertEqual(status, 200)
            token_payload = {
                "access_token": "access-token",
                "refresh_token": "rt-secret-raw",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": " ".join(
                    [
                        "https://www.googleapis.com/auth/gmail.readonly",
                        "https://www.googleapis.com/auth/gmail.modify",
                        "https://www.googleapis.com/auth/gmail.send",
                    ]
                ),
            }
            with patch("oauth._exchange_code", return_value=token_payload), patch("oauth.GmailProvider", return_value=FakeGmailProvider()):
                status, completed = handle_action(
                    data_root,
                    {
                        "action": "connections.complete_oauth",
                        "state": started["state"],
                        "code": "code",
                        "_workspace_id": "default",
                        "_app_secrets": {
                            "gmail-oauth-client-id": "client-id",
                            "gmail-oauth-client-secret": "client-secret",
                        },
                    },
                )

            self.assertEqual(status, 200)
            self.assertEqual(completed["status"], "connected")
            self.assertEqual(completed["platform_secret_writes"][0]["logical_name"], "gmail-refresh-token")
            public_payload = dict(completed)
            public_payload.pop("platform_secret_writes")
            self.assertNotIn("rt-secret-raw", str(public_payload))
            with connect(data_root) as db:
                credential = db.execute("SELECT * FROM oauth_credentials").fetchone()
            self.assertEqual(credential["secret_ref"], "platform:secret-alias/default-mail-gmail-refresh-token-mail_connection-mail_connection_gmail_person-example.com")
            self.assertEqual(credential["grant_id"], "grant:default:mail:gmail-refresh-token:mail_connection:mail_connection_gmail_person-example.com")
            self.assertNotIn("rt-secret-raw", credential["encrypted_token_json"])

    def test_gmail_sync_uses_refresh_secret_and_populates_cache(self) -> None:
        calls: list[str] = []

        def fake_transport(request) -> dict[str, object]:
            url = request.full_url
            calls.append(url)
            if url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token", "expires_in": 3600, "token_type": "Bearer"}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads?"):
                return {"threads": [{"id": "thread-1"}]}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads/thread-1?"):
                return {
                    "id": "thread-1",
                    "snippet": "Hello from Gmail",
                    "messages": [
                        {
                            "id": "msg-1",
                            "threadId": "thread-1",
                            "labelIds": ["INBOX", "UNREAD"],
                            "internalDate": "1710000000000",
                            "payload": {
                                "mimeType": "text/plain",
                                "headers": [
                                    {"name": "Subject", "value": "Gmail thread"},
                                    {"name": "From", "value": "Sender <sender@example.com>"},
                                    {"name": "To", "value": "Person <person@example.com>"},
                                ],
                                "body": {"data": "SGVsbG8gZnJvbSBHbWFpbA"},
                            },
                        }
                    ],
                }
            raise AssertionError(f"unexpected request {url}")

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )
            provider = GmailProvider(transport=fake_transport)
            result = provider.sync_incremental(
                data_root,
                "mail_connection_gmail_person-example.com",
                app_secrets={
                    "gmail-oauth-client-id": "client-id",
                    "gmail-oauth-client-secret": "client-secret",
                    "gmail-refresh-token": "refresh-token",
                },
            )
            self.assertEqual(result["synced_threads"], 1)
            status, payload = handle_action(
                data_root,
                {"action": "threads.get", "thread_id": "email_thread_gmail_mail_connection_gmail_person_example_com_thread_1"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["thread"]["subject"], "Gmail thread")
            self.assertEqual(payload["thread"]["messages"][0]["body_text"], "Hello from Gmail")
            self.assertGreaterEqual(calls.count("https://oauth2.googleapis.com/token"), 1)

    def test_gmail_sync_preserves_sanitized_html_and_attachment_metadata(self) -> None:
        def encoded(value: str) -> str:
            return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")

        html_body = (FIXTURE_ROOT / "newsletter_table_responsive.html").read_text(encoding="utf-8")

        def fake_transport(request) -> dict[str, object]:
            url = request.full_url
            if url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token", "expires_in": 3600, "token_type": "Bearer"}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads?"):
                return {"threads": [{"id": "thread-html"}]}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads/thread-html?"):
                return {
                    "id": "thread-html",
                    "snippet": "Hello HTML",
                    "messages": [
                        {
                            "id": "msg-html",
                            "threadId": "thread-html",
                            "labelIds": ["INBOX"],
                            "internalDate": "1710000000000",
                            "payload": {
                                "mimeType": "multipart/mixed",
                                "headers": [
                                    {"name": "Subject", "value": "HTML thread"},
                                    {"name": "From", "value": "Sender <sender@example.com>"},
                                    {"name": "To", "value": "Person <person@example.com>"},
                                ],
                                "parts": [
                                    {
                                        "mimeType": "multipart/alternative",
                                        "parts": [
                                            {"mimeType": "text/plain", "body": {"data": encoded("Hello HTML")}},
                                            {
                                                "mimeType": "text/html",
                                                "headers": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}],
                                                "body": {"data": encoded(html_body)},
                                            },
                                        ],
                                    },
                                    {
                                        "filename": "report.pdf",
                                        "mimeType": "application/pdf",
                                        "body": {"attachmentId": "att-report", "size": 1234},
                                    },
                                    {
                                        "filename": "logo.png",
                                        "mimeType": "image/png",
                                        "headers": [
                                            {"name": "Content-ID", "value": "<logo123>"},
                                            {"name": "Content-Disposition", "value": 'inline; filename="logo.png"'},
                                        ],
                                        "body": {"attachmentId": "att-logo", "size": 42},
                                    },
                                ],
                            },
                        }
                    ],
                }
            raise AssertionError(f"unexpected request {url}")

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )
            provider = GmailProvider(transport=fake_transport)
            provider.sync_incremental(
                data_root,
                "mail_connection_gmail_person-example.com",
                app_secrets={
                    "gmail-oauth-client-id": "client-id",
                    "gmail-oauth-client-secret": "client-secret",
                    "gmail-refresh-token": "refresh-token",
                },
            )

            status, payload = handle_action(
                data_root,
                {"action": "threads.get", "thread_id": "email_thread_gmail_mail_connection_gmail_person_example_com_thread_html"},
            )
            self.assertEqual(status, 200)
            message = payload["thread"]["messages"][0]
            self.assertEqual(message["body_text"], "Hello HTML")
            self.assertEqual(message["body_render_mode"], "html")
            self.assertEqual(message["body_html_rendered"], message["body_html_sanitized"])
            self.assertIn("<style>", message["body_html_gmail_sanitized"])
            self.assertTrue(message["body_html_original_available"])
            self.assertGreater(message["body_html_original_size"], 0)
            self.assertEqual(message["render_policy"]["version"], 2)
            self.assertEqual(message["render_policy"]["rendered_from"], "body_html_gmail_sanitized")
            self.assertIn("<style>", message["body_html_sanitized"])
            self.assertIn("@media only screen", message["body_html_sanitized"])
            self.assertIn(".desktop", message["body_html_sanitized"])
            self.assertIn('class="container"', message["body_html_sanitized"])
            self.assertIn('id="hero-card"', message["body_html_sanitized"])
            self.assertIn("<strong>HTML</strong>", message["body_html_sanitized"])
            self.assertIn("display: none", message["body_html_sanitized"])
            self.assertIn("max-height: 0", message["body_html_sanitized"])
            self.assertIn('cellpadding="0"', message["body_html_sanitized"])
            self.assertIn('bgcolor="#ffffff"', message["body_html_sanitized"])
            self.assertIn('style="color: #123456"', message["body_html_sanitized"])
            self.assertIn("background: #990000", message["body_html_sanitized"])
            self.assertIn('href="https://example.com/news"', message["body_html_sanitized"])
            self.assertIn("mail-blocked-image", message["body_html_sanitized"])
            self.assertIn("data-mail-image=", message["body_html_sanitized"])
            self.assertIn("data-mail-alt=", message["body_html_sanitized"])
            self.assertIn('data-mail-background-image="https://tracker.example/background.png"', message["body_html_sanitized"])
            self.assertNotIn("onclick", message["body_html_sanitized"])
            self.assertNotIn("<script", message["body_html_sanitized"])
            self.assertNotIn("src=", message["body_html_sanitized"])
            self.assertNotIn("@import", message["body_html_sanitized"])
            self.assertNotIn("url(", message["body_html_sanitized"])
            self.assertNotIn("u\\72l", message["body_html_sanitized"])
            self.assertNotIn("hero.png", message["body_html_sanitized"])
            attachments = {item["filename"]: item for item in message["attachments"]}
            self.assertEqual(attachments["report.pdf"]["size_bytes"], 1234)
            self.assertEqual(attachments["logo.png"]["size_bytes"], 42)
            inline_asset = message["inline_assets"][0]
            self.assertEqual(inline_asset["content_id"], "logo123")
            self.assertEqual(inline_asset["provider_attachment_id"], "att-logo")
            self.assertEqual(inline_asset["attachment_id"], attachments["logo.png"]["id"])
            with connect(data_root) as db:
                stored = db.execute(
                    """
                    SELECT body_html_original_bounded, body_html_gmail_sanitized, body_html_rendered, body_html_sanitized, render_policy_json
                    FROM messages
                    WHERE id = ?
                    """,
                    (message["id"],),
                ).fetchone()
            self.assertIn("<script>steal()</script>", stored["body_html_original_bounded"])
            self.assertIn('onclick="steal()"', stored["body_html_original_bounded"])
            self.assertIn("<style>", stored["body_html_gmail_sanitized"])
            self.assertEqual(stored["body_html_rendered"], stored["body_html_sanitized"])
            self.assertEqual(json.loads(stored["render_policy_json"])["version"], 2)

    def test_get_message_truncates_html_without_partial_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            html_body = "<div><p>" + ("Long body " * 80) + "</p></div>"
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "email_thread_gmail_mail_connection_gmail_person_example_com_thread_html",
                        "mail_connection_gmail_person-example.com",
                        "thread-html",
                        "Subject",
                        "[]",
                        now,
                        "",
                        0,
                        0,
                        "[]",
                        now,
                    ),
                )
                db.execute(
                    """
                    INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, body_html_sanitized, headers_json, has_attachments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "email_message_gmail_mail_connection_gmail_person_example_com_msg_html",
                        "email_thread_gmail_mail_connection_gmail_person_example_com_thread_html",
                        "msg-html",
                        "{}",
                        "[]",
                        now,
                        "Long body",
                        html_body,
                        "{}",
                        0,
                    ),
                )

            status, payload = handle_action(
                data_root,
                {"action": "messages.get", "message_id": "email_message_gmail_mail_connection_gmail_person_example_com_msg_html", "max_body_chars": 220},
            )

            self.assertEqual(status, 200)
            body_html = payload["message"]["body_html_sanitized"]
            self.assertTrue(payload["message"]["body_truncated"])
            self.assertEqual(payload["message"]["body_html_rendered"], body_html)
            self.assertEqual(payload["message"]["body_html_gmail_sanitized"], body_html)
            self.assertEqual(payload["message"]["render_policy"]["version"], 0)
            self.assertTrue(body_html.endswith("</p></div>"))
            self.assertNotIn("<p", body_html[-10:])

    def test_threads_get_preserves_reader_html_with_separate_text_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            body_text = "Plain body " * 80
            html_body = "<div><p>" + ("Reader HTML body " * 35) + "</p></div>"
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "email_thread_gmail_mail_connection_gmail_person_example_com_thread_reader_html",
                        "mail_connection_gmail_person-example.com",
                        "thread-reader-html",
                        "Subject",
                        "[]",
                        now,
                        "",
                        0,
                        0,
                        "[]",
                        now,
                    ),
                )
                db.execute(
                    """
                    INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, body_html_sanitized, headers_json, has_attachments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "email_message_gmail_mail_connection_gmail_person_example_com_msg_reader_html",
                        "email_thread_gmail_mail_connection_gmail_person_example_com_thread_reader_html",
                        "msg-reader-html",
                        "{}",
                        "[]",
                        now,
                        body_text,
                        html_body,
                        "{}",
                        0,
                    ),
                )

            status, payload = handle_action(
                data_root,
                {
                    "action": "threads.get",
                    "thread_id": "email_thread_gmail_mail_connection_gmail_person_example_com_thread_reader_html",
                    "max_body_chars": 220,
                    "max_body_html_chars": 1000,
                },
            )

            self.assertEqual(status, 200)
            message = payload["thread"]["messages"][0]
            self.assertEqual(message["body_text"], body_text[:220])
            self.assertEqual(message["body_html_sanitized"], html_body)
            self.assertEqual(message["body_html_rendered"], html_body)
            self.assertTrue(message["body_text_truncated"])
            self.assertFalse(message["body_html_truncated"])
            self.assertFalse(message["body_source_truncated"])
            self.assertTrue(message["body_truncated"])

    def test_gmail_sync_scopes_local_thread_ids_by_connection(self) -> None:
        def fake_transport(request) -> dict[str, object]:
            url = request.full_url
            if url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token", "expires_in": 3600, "token_type": "Bearer"}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads?"):
                return {"threads": [{"id": "shared-thread"}]}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads/shared-thread?"):
                return {
                    "id": "shared-thread",
                    "snippet": "Shared provider id",
                    "messages": [
                        {
                            "id": "shared-message",
                            "threadId": "shared-thread",
                            "labelIds": ["INBOX"],
                            "internalDate": "1710000000000",
                            "payload": {
                                "mimeType": "multipart/mixed",
                                "headers": [
                                    {"name": "Subject", "value": "Shared provider thread"},
                                    {"name": "From", "value": "Sender <sender@example.com>"},
                                    {"name": "To", "value": "Person <person@example.com>"},
                                ],
                                "parts": [
                                    {"mimeType": "text/plain", "body": {"data": "U2hhcmVk"}},
                                    {
                                        "filename": "shared.pdf",
                                        "mimeType": "application/pdf",
                                        "body": {"attachmentId": "shared-attachment", "size": 42},
                                    },
                                ],
                            },
                        }
                    ],
                }
            raise AssertionError(f"unexpected request {url}")

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.executemany(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, 'gmail', ?, ?, 'connected', '[]', ?, ?)
                    """,
                    [
                        ("mail_connection_gmail_a-example.com", "a@example.com", "a@example.com", now, now),
                        ("mail_connection_gmail_b-example.com", "b@example.com", "b@example.com", now, now),
                    ],
                )

            provider = GmailProvider(transport=fake_transport)
            secrets = {
                "gmail-oauth-client-id": "client-id",
                "gmail-oauth-client-secret": "client-secret",
                "gmail-refresh-token": "refresh-token",
            }
            provider.sync_incremental(data_root, "mail_connection_gmail_a-example.com", app_secrets=secrets)
            provider.sync_incremental(data_root, "mail_connection_gmail_b-example.com", app_secrets=secrets)

            with connect(data_root) as db:
                threads = db.execute(
                    "SELECT id, connection_id FROM threads WHERE provider_thread_id = ? ORDER BY connection_id",
                    ("shared-thread",),
                ).fetchall()
                messages = db.execute("SELECT id FROM messages WHERE provider_message_id = ? ORDER BY id", ("shared-message",)).fetchall()
                attachments = db.execute(
                    "SELECT id FROM attachments WHERE provider_attachment_id = ? ORDER BY id",
                    ("shared-attachment",),
                ).fetchall()

            self.assertEqual(len(threads), 2)
            self.assertEqual([row["connection_id"] for row in threads], ["mail_connection_gmail_a-example.com", "mail_connection_gmail_b-example.com"])
            self.assertEqual(len({row["id"] for row in threads}), 2)
            self.assertTrue(all(row["id"].startswith("email_thread_gmail_mail_connection_gmail_") for row in threads))
            self.assertEqual(len({row["id"] for row in messages}), 2)
            self.assertEqual(len({row["id"] for row in attachments}), 2)

    def test_gmail_sync_follows_thread_pages_until_requested_limit(self) -> None:
        calls: list[str] = []

        def thread_payload(thread_id: str) -> dict[str, object]:
            return {
                "id": thread_id,
                "snippet": f"Snippet {thread_id}",
                "messages": [
                    {
                        "id": f"msg-{thread_id}",
                        "threadId": thread_id,
                        "labelIds": ["INBOX"],
                        "internalDate": "1710000000000",
                        "payload": {
                            "mimeType": "text/plain",
                            "headers": [
                                {"name": "Subject", "value": f"Thread {thread_id}"},
                                {"name": "From", "value": "Sender <sender@example.com>"},
                                {"name": "To", "value": "Person <person@example.com>"},
                            ],
                            "body": {"data": "UGFnaW5hdGVk"},
                        },
                    }
                ],
            }

        def fake_transport(request) -> dict[str, object]:
            url = request.full_url
            calls.append(url)
            if url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token", "expires_in": 3600, "token_type": "Bearer"}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads?") and "pageToken=page-2" not in url:
                return {"threads": [{"id": "thread-1"}, {"id": "thread-2"}], "nextPageToken": "page-2"}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads?") and "pageToken=page-2" in url:
                return {"threads": [{"id": "thread-3"}]}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads/thread-"):
                thread_id = url.split("/threads/", 1)[1].split("?", 1)[0]
                return thread_payload(thread_id)
            raise AssertionError(f"unexpected request {url}")

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )

            result = GmailProvider(transport=fake_transport).sync_incremental(
                data_root,
                "mail_connection_gmail_person-example.com",
                app_secrets={
                    "gmail-oauth-client-id": "client-id",
                    "gmail-oauth-client-secret": "client-secret",
                    "gmail-refresh-token": "refresh-token",
                },
                max_threads=3,
            )

            self.assertEqual(result["synced_threads"], 3)
            self.assertFalse(result["has_more"])
            with connect(data_root) as db:
                thread_count = db.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"]
            self.assertEqual(thread_count, 3)
            self.assertTrue(any("pageToken=page-2" in url for url in calls))

    def test_gmail_lightweight_sync_does_not_replace_historic_cursor(self) -> None:
        def thread_payload(thread_id: str) -> dict[str, object]:
            return {
                "id": thread_id,
                "snippet": f"Snippet {thread_id}",
                "messages": [
                    {
                        "id": f"msg-{thread_id}",
                        "threadId": thread_id,
                        "labelIds": ["INBOX"],
                        "internalDate": "1710000000000",
                        "payload": {
                            "mimeType": "text/plain",
                            "headers": [
                                {"name": "Subject", "value": f"Thread {thread_id}"},
                                {"name": "From", "value": "Sender <sender@example.com>"},
                                {"name": "To", "value": "Person <person@example.com>"},
                            ],
                            "body": {"data": "UGFnaW5hdGVk"},
                        },
                    }
                ],
            }

        def fake_transport(request) -> dict[str, object]:
            url = request.full_url
            if url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token", "expires_in": 3600, "token_type": "Bearer"}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads?"):
                return {"threads": [{"id": "thread-1"}], "nextPageToken": "short-list-cursor"}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads/thread-1"):
                return thread_payload("thread-1")
            raise AssertionError(f"unexpected request {url}")

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO sync_state(connection_id, last_sync_at, last_error, cursor, last_full_sync_at, last_incremental_sync_at, provider_history_id)
                    VALUES (?, ?, '', ?, ?, ?, '')
                    """,
                    ("mail_connection_gmail_person-example.com", now, "historic-cursor", now, now),
                )

            result = GmailProvider(transport=fake_transport).sync_incremental(
                data_root,
                "mail_connection_gmail_person-example.com",
                app_secrets={
                    "gmail-oauth-client-id": "client-id",
                    "gmail-oauth-client-secret": "client-secret",
                    "gmail-refresh-token": "refresh-token",
                },
                max_threads=1,
                query="newer_than:30d",
                persist_cursor=False,
            )

            self.assertEqual(result["next_page_token"], "short-list-cursor")
            with connect(data_root) as db:
                cursor = db.execute(
                    "SELECT cursor FROM sync_state WHERE connection_id = ?",
                    ("mail_connection_gmail_person-example.com",),
                ).fetchone()["cursor"]
            self.assertEqual(cursor, "historic-cursor")

    def test_threads_list_uses_default_gmail_connection_for_lightweight_sync(self) -> None:
        calls: list[str] = []

        def fake_transport(request) -> dict[str, object]:
            url = request.full_url
            calls.append(url)
            if url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token", "expires_in": 3600, "token_type": "Bearer"}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads?"):
                return {"threads": [{"id": "thread-1"}]}
            if url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads/thread-1?"):
                return {
                    "id": "thread-1",
                    "snippet": "Implicit default connection",
                    "messages": [
                        {
                            "id": "msg-1",
                            "threadId": "thread-1",
                            "labelIds": ["INBOX"],
                            "internalDate": "1710000000000",
                            "payload": {
                                "mimeType": "text/plain",
                                "headers": [
                                    {"name": "Subject", "value": "Default Gmail"},
                                    {"name": "From", "value": "Sender <sender@example.com>"},
                                    {"name": "To", "value": "Person <person@example.com>"},
                                ],
                                "body": {"data": "SW1wbGljaXQgcmVmcmVzaA"},
                            },
                        }
                    ],
                }
            raise AssertionError(f"unexpected request {url}")

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            connection_id = "mail_connection_gmail_person-example.com"
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (connection_id, "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )

            with patch("backend.service.provider_for_connection", return_value=GmailProvider(transport=fake_transport)):
                status, payload = handle_action(
                    data_root,
                    {"action": "threads.list", "mailbox": "inbox", "_app_secrets": self._gmail_secrets()},
                )

            self.assertEqual(status, 200)
            self.assertEqual(payload["items"][0]["subject"], "Default Gmail")
            self.assertEqual(payload["items"][0]["connection_id"], connection_id)
            self.assertTrue(any(url == "https://oauth2.googleapis.com/token" for url in calls))
            self.assertTrue(any(url.startswith("https://gmail.googleapis.com/gmail/v1/users/me/threads?") for url in calls))

    def test_secret_resource_lookup_resolves_gmail_thread_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_thread_gmail_thread_1", "mail_connection_gmail_person-example.com", "thread-1", "Subject", "[]", now, "", 0, 0, "[]", now),
                )

            result = resolve_secret_resource(data_root, {"action": "mail_get_thread", "thread_id": "email_thread_gmail_thread_1"})

            self.assertTrue(result["requires_secrets"])
            self.assertEqual(result["resource_type"], "mail_connection")
            self.assertEqual(result["resource_id"], "mail_connection_gmail_person-example.com")

    def test_gmail_attachment_is_metadata_only_by_default(self) -> None:
        calls: list[str] = []

        def fake_transport(request) -> dict[str, object]:
            calls.append(request.full_url)
            raise AssertionError("metadata-only attachment fetch must not call Gmail")

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_thread_gmail_thread_1", "mail_connection_gmail_person-example.com", "thread-1", "Subject", "[]", now, "", 0, 0, "[]", now),
                )
                db.execute(
                    """
                    INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, headers_json, has_attachments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_message_gmail_msg_1", "email_thread_gmail_thread_1", "msg-1", "{}", "[]", now, "", "{}", 1),
                )
                db.execute(
                    """
                    INSERT INTO attachments(id, message_id, provider_attachment_id, filename, content_type, size_bytes, storage_state, storage_ref_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_attachment_gmail_msg_1_att_1", "email_message_gmail_msg_1", "att-1", "report.pdf", "application/pdf", 1024, "not_saved", "{}", now, now),
                )
            provider = GmailProvider(transport=fake_transport)

            result = provider.fetch_attachment(data_root, "mail_attachment_gmail_msg_1_att_1")

            self.assertEqual(result["status"], "metadata_only")
            self.assertEqual(result["size_bytes"], 1024)
            self.assertNotIn("data_base64url", result)
            self.assertEqual(calls, [])

    def test_gmail_attachment_fetch_returns_bounded_bytes_for_inline_reader(self) -> None:
        content = b"inline-logo"
        data_base64url = base64.urlsafe_b64encode(content).decode("ascii").rstrip("=")

        def fake_transport(request) -> dict[str, object]:
            if request.full_url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token"}
            if request.full_url.endswith("/messages/msg-1/attachments/att-1"):
                return {"data": data_base64url, "size": len(content)}
            raise AssertionError(f"Unexpected request {request.full_url}")

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            attachment_id = "mail_attachment_gmail_mail_connection_gmail_person_example_com_msg_1_att_1"
            self._insert_gmail_attachment(data_root, attachment_id=attachment_id, filename="logo.png", size_bytes=len(content))

            result = GmailProvider(transport=fake_transport).fetch_attachment(
                data_root,
                attachment_id,
                app_secrets=self._gmail_secrets(),
                metadata_only=False,
                max_bytes=100,
            )

            self.assertEqual(result["status"], "fetched")
            self.assertEqual(result["size_bytes"], len(content))
            self.assertEqual(result["data_base64url"], data_base64url)
            self.assertEqual(result["storage_state"], "not_saved")

    def test_gmail_attachment_save_to_storage_renames_on_collision(self) -> None:
        attachment_id = "mail_attachment_gmail_mail_connection_gmail_person_example_com_msg_1_att_1"
        content = b"fresh-pdf"

        def fake_transport(request) -> dict[str, object]:
            if request.full_url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token"}
            if request.full_url.endswith("/messages/msg-1/attachments/att-1"):
                return {"data": "ZnJlc2gtcGRm", "size": len(content)}
            raise AssertionError(f"Unexpected request {request.full_url}")

        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            data_root = workspace_root / "data" / "mail"
            generated_storage_root = workspace_root / "storage" / "generated"
            self._insert_gmail_attachment(data_root, attachment_id=attachment_id, filename="report.pdf", size_bytes=len(content))
            target_dir = generated_storage_root / "mail" / "attachments"
            target_dir.mkdir(parents=True)
            original_path = target_dir / "mail_attachment_gmail_mail_connection_gmail_person_example_com_msg_1_att_1-report.pdf"
            original_path.write_bytes(b"existing-pdf")

            result = GmailProvider(transport=fake_transport).fetch_attachment(
                data_root,
                attachment_id,
                app_secrets=self._gmail_secrets(),
                metadata_only=False,
                max_bytes=100,
                save_to_storage=True,
                generated_storage_root=generated_storage_root,
            )

            storage_ref = result["storage_ref"]
            self.assertEqual(result["status"], "saved")
            self.assertEqual(storage_ref["collision"], "renamed")
            self.assertEqual(storage_ref["filename"], "report.pdf")
            self.assertTrue(str(storage_ref["workspace_relative_path"]).startswith("storage/generated/mail/attachments/"))
            self.assertNotEqual(
                storage_ref["workspace_relative_path"],
                "storage/generated/mail/attachments/mail_attachment_gmail_mail_connection_gmail_person_example_com_msg_1_att_1-report.pdf",
            )
            self.assertEqual(original_path.read_bytes(), b"existing-pdf")
            saved_path = workspace_root / str(storage_ref["workspace_relative_path"])
            self.assertEqual(saved_path.read_bytes(), content)
            saved_path.resolve().relative_to((generated_storage_root / "mail" / "attachments").resolve())
            with connect(data_root) as db:
                stored_json = db.execute("SELECT storage_ref_json FROM attachments WHERE id = ?", (attachment_id,)).fetchone()["storage_ref_json"]
            self.assertEqual(json.loads(stored_json), storage_ref)

    def test_gmail_attachment_save_to_storage_sanitizes_traversal_filename(self) -> None:
        attachment_id = "mail_attachment_gmail_mail_connection_gmail_person_example_com_msg_1_att_1"
        content = b"safe-bytes"

        def fake_transport(request) -> dict[str, object]:
            if request.full_url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token"}
            if request.full_url.endswith("/messages/msg-1/attachments/att-1"):
                return {"data": "c2FmZS1ieXRlcw", "size": len(content)}
            raise AssertionError(f"Unexpected request {request.full_url}")

        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            data_root = workspace_root / "data" / "mail"
            generated_storage_root = workspace_root / "storage" / "generated"
            self._insert_gmail_attachment(data_root, attachment_id=attachment_id, filename="../../escape.txt", size_bytes=len(content))

            result = GmailProvider(transport=fake_transport).fetch_attachment(
                data_root,
                attachment_id,
                app_secrets=self._gmail_secrets(),
                metadata_only=False,
                max_bytes=100,
                save_to_storage=True,
                generated_storage_root=generated_storage_root,
            )

            storage_ref = result["storage_ref"]
            self.assertEqual(result["status"], "saved")
            self.assertEqual(storage_ref["filename"], "../../escape.txt")
            self.assertTrue(str(storage_ref["workspace_relative_path"]).startswith("storage/generated/mail/attachments/"))
            self.assertNotIn("..", Path(str(storage_ref["workspace_relative_path"])).parts)
            saved_path = workspace_root / str(storage_ref["workspace_relative_path"])
            self.assertEqual(saved_path.name, "mail_attachment_gmail_mail_connection_gmail_person_example_com_msg_1_att_1-escape.txt")
            self.assertEqual(saved_path.read_bytes(), content)
            saved_path.resolve().relative_to((generated_storage_root / "mail" / "attachments").resolve())
            self.assertFalse((workspace_root / "escape.txt").exists())
            with connect(data_root) as db:
                stored_json = db.execute("SELECT storage_state, storage_ref_json FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
            self.assertEqual(stored_json["storage_state"], "saved")
            self.assertEqual(json.loads(stored_json["storage_ref_json"]), storage_ref)

    def test_gmail_attachment_max_bytes_uses_decoded_payload_size(self) -> None:
        attachment_id = "mail_attachment_gmail_mail_connection_gmail_person_example_com_msg_1_att_1"
        content = b"x" * 64
        data_base64url = base64.urlsafe_b64encode(content).decode("ascii").rstrip("=")

        def fake_transport(request) -> dict[str, object]:
            if request.full_url == "https://oauth2.googleapis.com/token":
                return {"access_token": "access-token"}
            if request.full_url.endswith("/messages/msg-1/attachments/att-1"):
                return {"data": data_base64url, "size": 1}
            raise AssertionError(f"Unexpected request {request.full_url}")

        for save_to_storage in (False, True):
            with self.subTest(save_to_storage=save_to_storage):
                with tempfile.TemporaryDirectory() as tmp:
                    workspace_root = Path(tmp)
                    data_root = workspace_root / "data" / "mail"
                    generated_storage_root = workspace_root / "storage" / "generated"
                    self._insert_gmail_attachment(data_root, attachment_id=attachment_id, filename="report.pdf", size_bytes=1)

                    result = GmailProvider(transport=fake_transport).fetch_attachment(
                        data_root,
                        attachment_id,
                        app_secrets=self._gmail_secrets(),
                        metadata_only=False,
                        max_bytes=10,
                        save_to_storage=save_to_storage,
                        generated_storage_root=generated_storage_root,
                    )

                    self.assertEqual(result["status"], "too_large")
                    self.assertEqual(result["size_bytes"], len(content))
                    self.assertEqual(result["max_bytes"], 10)
                    self.assertNotIn("data_base64url", result)
                    self.assertFalse((generated_storage_root / "mail" / "attachments").exists())
                    with connect(data_root) as db:
                        stored_json = db.execute("SELECT storage_state, storage_ref_json FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
                    self.assertEqual(stored_json["storage_state"], "not_saved")
                    self.assertEqual(json.loads(stored_json["storage_ref_json"]), {})

    def test_attachment_max_bytes_is_capped_at_runtime(self) -> None:
        class FakeProvider:
            def fetch_attachment(self, data_root: Path, attachment_id: str, **kwargs) -> dict[str, object]:
                return {
                    "attachment_id": attachment_id,
                    "metadata_only": kwargs["metadata_only"],
                    "max_bytes": kwargs["max_bytes"],
                }

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
                )
                db.execute(
                    """
                    INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_thread_gmail_thread_1", "mail_connection_gmail_person-example.com", "thread-1", "Subject", "[]", now, "", 0, 0, "[]", now),
                )
                db.execute(
                    """
                    INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, headers_json, has_attachments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("email_message_gmail_msg_1", "email_thread_gmail_thread_1", "msg-1", "{}", "[]", now, "", "{}", 1),
                )
                db.execute(
                    """
                    INSERT INTO attachments(id, message_id, provider_attachment_id, filename, content_type, size_bytes, storage_state, storage_ref_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_attachment_gmail_msg_1_att_1", "email_message_gmail_msg_1", "att-1", "report.pdf", "application/pdf", 1024, "not_saved", "{}", now, now),
                )

            with patch("backend.service.provider_for_connection", return_value=FakeProvider()):
                status, payload = handle_action(
                    data_root,
                    {
                        "action": "mail_get_attachment",
                        "attachment_id": "mail_attachment_gmail_msg_1_att_1",
                        "metadata_only": False,
                        "max_bytes": 999_999_999,
                    },
                )

            self.assertEqual(status, 200)
            self.assertFalse(payload["fetch"]["metadata_only"])
            self.assertEqual(payload["fetch"]["max_bytes"], 10_000_000)

    def _insert_gmail_attachment(self, data_root: Path, *, attachment_id: str, filename: str, size_bytes: int) -> None:
        ensure_schema(data_root)
        now = now_timestamp()
        with connect(data_root) as db:
            db.execute(
                """
                INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("mail_connection_gmail_person-example.com", "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
            )
            db.execute(
                """
                INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "email_thread_gmail_mail_connection_gmail_person_example_com_thread_1",
                    "mail_connection_gmail_person-example.com",
                    "thread-1",
                    "Subject",
                    "[]",
                    now,
                    "",
                    0,
                    0,
                    "[]",
                    now,
                ),
            )
            db.execute(
                """
                INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, headers_json, has_attachments)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "email_message_gmail_mail_connection_gmail_person_example_com_msg_1",
                    "email_thread_gmail_mail_connection_gmail_person_example_com_thread_1",
                    "msg-1",
                    "{}",
                    "[]",
                    now,
                    "",
                    "{}",
                    1,
                ),
            )
            db.execute(
                """
                INSERT INTO attachments(id, message_id, provider_attachment_id, filename, content_type, size_bytes, storage_state, storage_ref_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    "email_message_gmail_mail_connection_gmail_person_example_com_msg_1",
                    "att-1",
                    filename,
                    "application/octet-stream",
                    size_bytes,
                    "not_saved",
                    "{}",
                    now,
                    now,
                ),
            )

    def _gmail_secrets(self) -> dict[str, object]:
        return {
            "gmail-oauth-client-id": "client-id",
            "gmail-oauth-client-secret": "client-secret",
            "gmail-refresh-token": "refresh-token",
        }

    def _insert_gmail_fixture(self, data_root: Path) -> str:
        ensure_schema(data_root)
        now = now_timestamp()
        connection_id = "mail_connection_gmail_person-example.com"
        labels = [
            ("label_gmail_inbox", "INBOX", "Inbox", "inbox"),
            ("label_gmail_sent", "SENT", "Sent", "sent"),
            ("label_gmail_drafts", "DRAFT", "Drafts", "drafts"),
            ("label_gmail_starred", "STARRED", "Starred", "starred"),
            ("label_gmail_trash", "TRASH", "Trash", "trash"),
        ]
        with connect(data_root) as db:
            db.execute(
                """
                INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (connection_id, "gmail", "person@example.com", "person@example.com", "connected", "[]", now, now),
            )
            db.executemany(
                "INSERT INTO folders(id, connection_id, provider_folder_id, name, canonical, folder_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (f"folder_gmail_{canonical}", connection_id, provider_id, name, canonical, canonical, now, now)
                    for _, provider_id, name, canonical in labels
                ],
            )
            db.executemany(
                "INSERT INTO labels(id, connection_id, provider_label_id, name, canonical) VALUES (?, ?, ?, ?, ?)",
                [(label_id, connection_id, provider_id, name, canonical) for label_id, provider_id, name, canonical in labels],
            )
            db.executemany(
                """
                INSERT INTO threads(id, connection_id, provider_thread_id, subject, participants_json, last_message_at, snippet, unread, starred, labels_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "email_thread_gmail_fixture_welcome",
                        connection_id,
                        "provider-fixture-welcome",
                        "Welcome to Maverick Mail",
                        '[{"name":"Sender","email":"sender@example.com"},{"name":"Person","email":"person@example.com"}]',
                        now,
                        "A native Maverick mail workspace with CLI, MCP, references, and local storage.",
                        1,
                        1,
                        '["inbox", "starred"]',
                        now,
                    ),
                    (
                        "email_thread_gmail_fixture_ops",
                        connection_id,
                        "provider-fixture-ops",
                        "Mail app implementation notes",
                        '[{"name":"Product","email":"product@example.com"},{"name":"Person","email":"person@example.com"}]',
                        now,
                        "Gmail OAuth is the supported provider integration.",
                        0,
                        0,
                        '["inbox"]',
                        now,
                    ),
                ],
            )
            db.executemany(
                """
                INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, headers_json, has_attachments)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "email_message_gmail_fixture_welcome_1",
                        "email_thread_gmail_fixture_welcome",
                        "provider-message-welcome-1",
                        '{"name":"Sender","email":"sender@example.com"}',
                        '[{"name":"Person","email":"person@example.com"}]',
                        now,
                        "This app uses Gmail provider cache records for local tests.",
                        "{}",
                        0,
                    ),
                    (
                        "email_message_gmail_fixture_ops_1",
                        "email_thread_gmail_fixture_ops",
                        "provider-message-ops-1",
                        '{"name":"Product","email":"product@example.com"}',
                        '[{"name":"Person","email":"person@example.com"}]',
                        now,
                        "Configure Google OAuth secrets through Vault/Core Secrets.",
                        "{}",
                        0,
                    ),
                ],
            )
        return connection_id

    def test_mcp_gmail_secret_selectors_match_remote_fetch_semantics(self) -> None:
        schemas = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))

        thread_selectors = schemas["tools"]["mail_get_thread"]["secret_selectors"]
        attachment_selectors = schemas["tools"]["mail_get_attachment"]["secret_selectors"]
        thread_properties = schemas["tools"]["mail_get_thread"]["input_schema"]["properties"]

        self.assertTrue(all("when" not in selector for selector in thread_selectors))
        self.assertTrue(all(selector.get("when") == {"metadata_only": False} for selector in attachment_selectors))
        self.assertEqual(thread_properties["max_body_html_chars"]["maximum"], 250000)

    def test_reference_resolve_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            self._insert_gmail_fixture(data_root)
            _, listed = handle_action(data_root, {"action": "threads.list"})
            thread_id = listed["items"][0]["id"]
            status, payload = handle_action(
                data_root,
                {"action": "reference_resolve", "entity_type": "email_thread", "entity_id": thread_id},
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["item"]["entity_type"], "email_thread")
            self.assertIn("/app/mail?thread=", payload["item"]["deep_link"])

    def test_reference_search_returns_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            self._insert_gmail_fixture(data_root)
            status, created = handle_action(
                data_root,
                {
                    "action": "drafts.create",
                    "to": [{"email": "customer@example.com"}],
                    "subject": "Draft reference needle",
                    "body_text": "Drafts should be searchable references.",
                },
            )
            self.assertEqual(status, 201)
            status, payload = handle_action(data_root, {"action": "reference_search", "query": "needle"})
            self.assertEqual(status, 200)
            draft_refs = [item for item in payload["items"] if item["entity_type"] == "mail_draft"]
            self.assertEqual(draft_refs[0]["entity_id"], created["draft"]["id"])

    def test_frontend_entrypoint_mounts_mail_app(self) -> None:
        main_source = (APP_ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
        self.assertIn("from './App'", main_source)
        self.assertNotIn("New record", main_source)

    def test_frontend_reader_uses_thread_toolbar_without_inline_composer(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("const [readerPlain, setReaderPlain] = useState(false);", app_source)
        self.assertIn("const [readerShowImages, setReaderShowImages] = useState(false);", app_source)
        self.assertIn("modifySelected([], ['inbox'])", app_source)
        self.assertIn("modifySelected(['trash'], ['inbox'])", app_source)
        self.assertNotIn("composerMode", app_source)
        self.assertNotIn("function startReply()", app_source)
        self.assertNotIn("function startForward()", app_source)

    def test_frontend_opens_cached_thread_without_secret_refresh(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("const openThread = useCallback(async (threadId: string, connectionId?: string, refresh = false)", app_source)
        self.assertIn("...(refresh && connectionId ? secretRequestForConnectionId(connectionId) : noSecretRequest())", app_source)
        self.assertIn("openThread(selectedThread.id, selectedThread.connection_id, true)", app_source)

    def test_frontend_add_account_lives_in_sidebar_and_opens_provider_modal(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        styles = (APP_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        footer_source = (APP_ROOT / "frontend" / "src" / "widgets" / "mail-sidebar-footer" / "main.tsx").read_text(encoding="utf-8")
        self.assertNotIn("add-account-button", app_source)
        self.assertNotIn("account-panel", app_source)
        self.assertNotIn("privateEmailForm", app_source)
        self.assertNotIn("provider-tabs", styles)
        self.assertNotIn("private-email-grid", styles)
        self.assertIn("const PRIMARY_ACTION_LABEL = 'Connect Account';", footer_source)
        self.assertIn("add_account: true", footer_source)
        self.assertIn("maverick.widget.open-app", footer_source)
        self.assertIn("mail-account-modal", app_source)
        self.assertIn("Open OAuth", app_source)
        self.assertIn("Open Vault", app_source)
        self.assertIn("action: MAIL_BACKEND_ACTIONS.connectionsPrepareImapSmtp", app_source)
        self.assertIn("openBlankAuthorizationWindow()", app_source)
        self.assertIn("maverick.app.external-url", app_source)
        self.assertNotIn("window.location.assign(payload.authorization_url)", app_source)

    def test_frontend_sidebar_removes_disconnected_accounts_with_trash(self) -> None:
        api_source = (APP_ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
        sidebar_source = (APP_ROOT / "frontend" / "src" / "widgets" / "mail-sidebar" / "main.tsx").read_text(encoding="utf-8")
        self.assertIn("connectionsDelete: 'connections.delete'", api_source)
        self.assertIn("Trash2", sidebar_source)
        self.assertIn("const removeDisconnected = targetConnection.status === 'disconnected';", sidebar_source)
        self.assertIn("action: MAIL_BACKEND_ACTIONS.connectionsDelete", sidebar_source)
        self.assertIn("aria-label={isDisconnected ? `Remove ${node.label}` : `Disconnect ${node.label}`}", sidebar_source)
        self.assertIn("disabled={Boolean(activeOperation)}", sidebar_source)

    def test_frontend_renders_html_email_in_isolated_frame(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        styles = (APP_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("function MailHtmlFrame", app_source)
        self.assertIn('sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin"', app_source)
        self.assertIn("<MailHtmlFrame htmlBody={renderedHtml} />", app_source)
        self.assertIn("INLINE_IMAGE_MAX_BYTES", app_source)
        self.assertIn("inlineImageDataUrl", app_source)
        self.assertIn("MAIL_BACKEND_ACTIONS.attachmentsGet", app_source)
        self.assertIn("metadata_only: false", app_source)
        self.assertIn("Loading inline image", app_source)
        self.assertIn("data:", app_source)
        self.assertIn("ResizeObserver", app_source)
        self.assertIn("EMAIL_FRAME_MAX_WIDTH", app_source)
        self.assertIn("contentWidth > parentWidth + 1", app_source)
        self.assertIn("style={{ height, width: frameWidth ? `${frameWidth}px` : undefined }}", app_source)
        self.assertIn("showRemoteImages", app_source)
        self.assertIn("const [readerPlain, setReaderPlain] = useState(false);", app_source)
        self.assertIn("const [readerShowImages, setReaderShowImages] = useState(false);", app_source)
        self.assertIn("setReaderPlain((value) => !value)", app_source)
        self.assertIn("setReaderShowImages((value) => !value)", app_source)
        self.assertIn("Show images", app_source)
        self.assertIn("mail-blocked-image", app_source)
        self.assertIn("data-mail-image", app_source)
        self.assertIn("reader-view-actions", app_source)
        self.assertIn("replaceWith(image)", app_source)
        self.assertIn("data-mail-background-image", app_source)
        self.assertIn("backgroundImage", app_source)
        self.assertIn("referrerPolicy = 'no-referrer'", app_source)
        self.assertIn("background: #fff;", styles)
        self.assertIn("overflow-x: auto;", styles)
        self.assertIn("min-width: 100%;", styles)
        self.assertIn("flex-wrap: wrap;", styles)
        self.assertIn(".reader-view-actions", styles)
        self.assertNotIn("color: #111827;", app_source)
        self.assertNotIn("line-height: 1.45;", app_source)
        self.assertNotIn("border-spacing: 0;", app_source)
        self.assertNotIn(".message-html :where(td, th)", styles)

    def test_frontend_reader_has_gmail_like_phase_eight_controls(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        styles = (APP_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("function foldQuotedHtml", app_source)
        self.assertIn("mail-quote-fold", app_source)
        self.assertIn("Show quoted text", app_source)
        self.assertIn("function MailThreadMessage", app_source)
        self.assertIn('className="message-head"', app_source)
        self.assertIn("function MailMessageBody", app_source)
        self.assertIn("readerHasHtml", app_source)
        self.assertIn("readerHasRemoteImages", app_source)
        self.assertIn("readerPlain", app_source)
        self.assertIn("readerShowImages", app_source)
        self.assertIn("reader-thread-actions", app_source)
        self.assertIn('aria-label="Archive"', app_source)
        self.assertIn('aria-label="Move to trash"', app_source)
        self.assertIn("Show trimmed content", app_source)
        self.assertIn("MAIL_BACKEND_ACTIONS.messagesGet", app_source)
        self.assertIn("READER_FULL_TEXT_BODY_CHARS", app_source)
        self.assertIn(".reader-view-actions", styles)
        self.assertIn(".reader-thread-actions", styles)
        self.assertIn(".message-trimmed", styles)
        self.assertIn(".message-meta", styles)
        self.assertIn("grid-template-columns: minmax(260px, 340px) minmax(760px, 1fr);", styles)


if __name__ == "__main__":
    unittest.main()
