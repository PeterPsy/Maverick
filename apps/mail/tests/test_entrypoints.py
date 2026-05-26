"""Mail app service tests."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))
from backend.service import handle_action, resolve_secret_resource
from backend.service import app_events_for_action
from backend.database import connect, ensure_schema, health_payload, now_timestamp
from backend.providers.gmail import GmailProvider


class MailServiceTest(unittest.TestCase):
    def test_fresh_install_has_no_demo_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "threads.list", "mailbox": "inbox"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["items"], [])
            status, payload = handle_action(Path(tmp), {"action": "connections.list"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["items"], [])

    def test_bootstrap_mock_lists_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "connections.bootstrap_mock"})
            self.assertEqual(status, 201)
            self.assertTrue(payload["mock"]["created"])
            status, payload = handle_action(Path(tmp), {"action": "threads.list", "mailbox": "inbox"})
            self.assertEqual(status, 200)
            self.assertGreaterEqual(len(payload["items"]), 1)
            self.assertIn("subject", payload["items"][0])

    def test_disconnect_mock_marks_connection_and_preserves_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            handle_action(data_root, {"action": "connections.bootstrap_mock"})

            status, payload = handle_action(data_root, {"action": "connections.disconnect", "connection_id": "mail_connection_demo"})

            self.assertEqual(status, 200)
            self.assertEqual(payload["disconnect"]["status"], "disconnected")
            self.assertEqual(payload["disconnect"]["connection"]["status"], "disconnected")
            self.assertGreaterEqual(payload["disconnect"]["cache"]["thread_count"], 1)
            self.assertEqual(payload["disconnect"]["core_secret_revocation"]["status"], "not_supported_by_app_backend")
            status, listed = handle_action(data_root, {"action": "threads.list", "connection_id": "mail_connection_demo"})
            self.assertEqual(status, 200)
            self.assertGreaterEqual(len(listed["items"]), 1)
            status, connections = handle_action(data_root, {"action": "connections.list"})
            self.assertEqual(status, 200)
            mock_provider = [item for item in connections["providers"] if item["provider"] == "mock"][0]
            self.assertFalse(mock_provider["connected"])
            with connect(data_root) as db:
                audit_row = db.execute(
                    "SELECT detail_json FROM audit_log WHERE action = ? AND target_id = ?",
                    ("connections.disconnect", "mail_connection_demo"),
                ).fetchone()
            self.assertIsNotNone(audit_row)
            self.assertTrue(json.loads(audit_row["detail_json"])["cache_preserved"])

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

    def test_threads_list_returns_pagination_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            handle_action(data_root, {"action": "connections.bootstrap_mock"})
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

    def test_legacy_demo_connection_is_migrated_to_mock_provider(self) -> None:
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
            self.assertEqual(payload["items"][0]["provider"], "mock")
            self.assertEqual(payload["items"][0]["email_address"], "mock@example.com")

    def test_get_thread_returns_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handle_action(Path(tmp), {"action": "connections.bootstrap_mock"})
            _, listed = handle_action(Path(tmp), {"action": "threads.list"})
            thread_id = listed["items"][0]["id"]
            status, payload = handle_action(Path(tmp), {"action": "threads.get", "thread_id": thread_id})
            self.assertEqual(status, 200)
            self.assertEqual(payload["thread"]["id"], thread_id)
            self.assertGreaterEqual(len(payload["thread"]["messages"]), 1)

    def test_create_and_preview_send_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            handle_action(data_root, {"action": "connections.bootstrap_mock"})
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

    def test_mail_send_confirm_requires_recipient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            handle_action(data_root, {"action": "connections.bootstrap_mock"})
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
            handle_action(data_root, {"action": "connections.bootstrap_mock"})
            ensure_schema(data_root)
            now = now_timestamp()
            with connect(data_root) as db:
                db.execute(
                    """
                    INSERT INTO drafts(id, connection_id, to_json, cc_json, bcc_json, subject, body_text, status, dirty, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("mail_draft_missing_recipients", "mail_connection_demo", "[]", "[]", "[]", "No recipient", "Blocked.", "draft", 1, now, now),
                )
            status, payload = handle_action(data_root, {"action": "drafts.send", "draft_id": "mail_draft_missing_recipients", "confirm": True})
            self.assertEqual(status, 400)
            self.assertIn("recipient", payload["detail"])

    def test_reply_draft_derives_recipient_from_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            handle_action(data_root, {"action": "connections.bootstrap_mock"})
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
            self.assertNotEqual(payload["draft"]["to"][0]["email"], "mock@example.com")

    def test_mcp_draft_action_emits_data_event(self) -> None:
        events = app_events_for_action("mail_create_draft")
        self.assertEqual(events, [{"type": "maverick.app.data-changed", "owner_app_id": "mail", "resource": "drafts"}])

    def test_disconnect_action_emits_connection_event(self) -> None:
        events = app_events_for_action("connections.disconnect")
        self.assertEqual(events, [{"type": "maverick.app.data-changed", "owner_app_id": "mail", "resource": "connections"}])

    def test_schema_includes_provider_and_link_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "health.check"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["schema_version"], "3")
            self.assertEqual(payload["health_status"], "healthy")
            self.assertEqual(payload["database"], "mail.sqlite")

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

    def test_mcp_gmail_secret_selectors_match_remote_fetch_semantics(self) -> None:
        schemas = json.loads((APP_ROOT / "mcp" / "tool_schemas.json").read_text(encoding="utf-8"))

        thread_selectors = schemas["tools"]["mail_get_thread"]["secret_selectors"]
        attachment_selectors = schemas["tools"]["mail_get_attachment"]["secret_selectors"]

        self.assertTrue(all("when" not in selector for selector in thread_selectors))
        self.assertTrue(all(selector.get("when") == {"metadata_only": False} for selector in attachment_selectors))

    def test_reference_resolve_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            handle_action(data_root, {"action": "connections.bootstrap_mock"})
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
            handle_action(data_root, {"action": "connections.bootstrap_mock"})
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


if __name__ == "__main__":
    unittest.main()
