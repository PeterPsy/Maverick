"""Tests for the Gmail App."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest

from core.api.app_mounts import _apply_app_secret_writes, _resolve_app_secret_payload
from core.apps.contracts import parse_app_contract_file
from core.secrets.store import MongoSecretStore, SecretCollections
from core.shared.json_file_collection import JsonFileCollection
from core.shared.entrypoints import run_json_entrypoint


REPO_ROOT = Path(__file__).resolve().parents[1]
GMAIL_APP_ROOT = REPO_ROOT / "apps" / "gmail-app"
sys.path.insert(0, str(GMAIL_APP_ROOT / "backend"))

from gmail_client import thread_from_gmail_payload  # noqa: E402


class GmailAppTestCase(unittest.TestCase):
    def run_backend(self, data_root: Path, body: dict) -> dict:
        return run_json_entrypoint(
            GMAIL_APP_ROOT / "backend" / "app_backend.py",
            payload={"workspace_id": "default", "data_root": str(data_root), "body": body},
            cwd=GMAIL_APP_ROOT,
        )

    def test_contract_declares_gmail_app_surfaces(self) -> None:
        parsed = parse_app_contract_file(GMAIL_APP_ROOT)

        self.assertEqual(parsed.app_id, "gmail-app")
        self.assertEqual(parsed.contract.distribution.mode, "source_available")
        self.assertEqual(parsed.contract.distribution.source_access, "forkable")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertIn("gmail_app_send_approved", parsed.contract.capabilities.mcp_tools)
        self.assertIn("gmail_app_oauth_exchange", parsed.contract.capabilities.mcp_tools)
        self.assertIn("gmail_app_latest_threads", parsed.contract.capabilities.mcp_tools)
        self.assertIn("gmail_app_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertIn("gmail_app_reference_summarize", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["gmail-app"])
        self.assertEqual(parsed.contract.storage.storage_kind, "sqlite")
        self.assertIn("data/gmail-app/gmail.sqlite", parsed.contract.storage.primary_paths)
        self.assertEqual({item.entity_type for item in parsed.contract.capabilities.reference_entities}, {"thread", "message"})

    def test_install_hook_is_idempotent_and_creates_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"
            payload = {"data_root": str(data_root)}

            first = run_json_entrypoint(GMAIL_APP_ROOT / "hooks" / "install.py", payload=payload, cwd=GMAIL_APP_ROOT)
            second = run_json_entrypoint(GMAIL_APP_ROOT / "hooks" / "install.py", payload=payload, cwd=GMAIL_APP_ROOT)
            health = run_json_entrypoint(GMAIL_APP_ROOT / "hooks" / "health_check.py", payload=payload, cwd=GMAIL_APP_ROOT)

            self.assertEqual(first["status"], "ok")
            self.assertEqual(second["status"], "ok")
            self.assertEqual(health["schema_version"], "1")
            self.assertTrue((data_root / "gmail.sqlite").is_file())
            self.assertTrue((data_root / "state.json").is_file())

    def test_search_summarize_and_list_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"

            search = self.run_backend(data_root, {"action": "threads.search", "gmail_client_mode": "fake", "query": "CRM"})["json"]
            latest = self.run_backend(data_root, {"action": "threads.latest", "gmail_client_mode": "fake", "limit": 100})["json"]
            thread_id = search["threads"][0]["id"]
            summary = self.run_backend(data_root, {"action": "threads.summarize", "thread_id": thread_id})["json"]
            suggestions = self.run_backend(data_root, {"action": "suggestions.list"})["json"]["suggestions"]

            self.assertEqual(search["threads"][0]["subject"], "Allineamento progetto CRM")
            self.assertEqual(latest["threads"][0]["id"], "thread_demo_1")
            self.assertEqual(latest["source"], "cache")
            self.assertIn("follow-up commerciale", summary["summary"]["summary"])
            self.assertTrue(any(item["kind"] == "activity" for item in suggestions))
            self.assertTrue(any(item["kind"] == "contact" for item in suggestions))

    def test_threads_include_latest_sender_metadata_and_can_be_marked_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"
            fake_threads = [
                {
                    "id": "thread_unread_1",
                    "subject": "Inbound message",
                    "snippet": "Please review this.",
                    "updated_at": "2026-04-21T10:00:00Z",
                    "labels": ["INBOX", "UNREAD"],
                    "is_unread": True,
                    "messages": [
                        {
                            "id": "msg_unread_1",
                            "from_email": "client@example.com",
                            "to_emails": ["user@example.com"],
                            "snippet": "Please review this.",
                            "body_text": "Please review this.",
                            "received_at": "2026-04-21T10:00:00Z",
                            "is_unread": True,
                        }
                    ],
                },
                {
                    "id": "thread_sent_1",
                    "subject": "Sent message",
                    "snippet": "I sent this.",
                    "updated_at": "2026-04-21T11:00:00Z",
                    "labels": ["SENT"],
                    "messages": [
                        {
                            "id": "msg_sent_1",
                            "from_email": "user@example.com",
                            "to_emails": ["client@example.com"],
                            "snippet": "I sent this.",
                            "body_text": "I sent this.",
                            "received_at": "2026-04-21T11:00:00Z",
                        }
                    ],
                },
                {
                    "id": "thread_spam_1",
                    "subject": "Spam message",
                    "snippet": "You won.",
                    "updated_at": "2026-04-21T12:00:00Z",
                    "labels": ["SPAM", "UNREAD"],
                    "messages": [
                        {
                            "id": "msg_spam_1",
                            "from_email": "spam@example.com",
                            "to_emails": ["user@example.com"],
                            "snippet": "You won.",
                            "body_text": "You won.",
                            "received_at": "2026-04-21T12:00:00Z",
                            "is_unread": True,
                        }
                    ],
                },
            ]

            loaded = self.run_backend(data_root, {"action": "threads.latest", "gmail_client_mode": "fake", "fake_threads": fake_threads, "force_refresh": True})["json"]
            cached = self.run_backend(data_root, {"action": "threads.latest", "limit": 100})["json"]
            spam = self.run_backend(data_root, {"action": "threads.spam", "gmail_client_mode": "fake", "fake_threads": fake_threads, "force_refresh": True})["json"]
            marked = self.run_backend(data_root, {"action": "threads.mark_read", "thread_id": "thread_unread_1"})["json"]["thread"]

            inbound = next(item for item in loaded["threads"] if item["id"] == "thread_unread_1")
            sent = next(item for item in cached["threads"] if item["id"] == "thread_sent_1")

            self.assertNotIn("thread_spam_1", {item["id"] for item in loaded["threads"]})
            self.assertNotIn("thread_spam_1", {item["id"] for item in cached["threads"]})
            self.assertEqual([item["id"] for item in spam["threads"]], ["thread_spam_1"])
            self.assertEqual(inbound["from_email"], "client@example.com")
            self.assertEqual(inbound["to_emails"], ["user@example.com"])
            self.assertTrue(inbound["is_unread"])
            self.assertEqual(sent["from_email"], "user@example.com")
            self.assertEqual(sent["to_emails"], ["client@example.com"])
            self.assertFalse(marked["is_unread"])
            self.assertFalse(marked["messages"][0]["is_unread"])

    def test_thread_pages_sync_and_cache_paginated_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"
            fake_threads = []
            for index in range(3):
                fake_threads.append(
                    {
                        "id": f"thread_page_{index}",
                        "subject": f"Inbox page {index}",
                        "snippet": f"Page snippet {index}",
                        "updated_at": f"2026-04-21T1{index}:00:00Z",
                        "labels": ["INBOX"],
                        "messages": [
                            {
                                "id": f"msg_page_{index}",
                                "from_email": f"person{index}@example.com",
                                "to_emails": ["user@example.com"],
                                "snippet": f"Page snippet {index}",
                                "body_text": f"Page body {index}",
                                "received_at": f"2026-04-21T1{index}:00:00Z",
                            }
                        ],
                    }
                )
            fake_threads.insert(
                0,
                {
                    "id": "thread_promo_newer",
                    "subject": "Promo newer",
                    "snippet": "Not inbox page",
                    "updated_at": "2026-04-21T19:00:00Z",
                    "labels": ["INBOX", "CATEGORY_PROMOTIONS"],
                    "messages": [
                        {
                            "id": "msg_promo_newer",
                            "from_email": "promo@example.com",
                            "to_emails": ["user@example.com"],
                            "snippet": "Not inbox page",
                            "body_text": "Not inbox page",
                            "received_at": "2026-04-21T19:00:00Z",
                        }
                    ],
                },
            )
            fake_threads.append(
                {
                    "id": "thread_spam_page",
                    "subject": "Spam page",
                    "snippet": "Not inbox page",
                    "updated_at": "2026-04-21T09:00:00Z",
                    "labels": ["SPAM"],
                    "messages": [
                        {
                            "id": "msg_spam_page",
                            "from_email": "spam@example.com",
                            "to_emails": ["user@example.com"],
                            "snippet": "Not inbox page",
                            "body_text": "Not inbox page",
                            "received_at": "2026-04-21T09:00:00Z",
                        }
                    ],
                },
            )

            first = self.run_backend(
                data_root,
                {
                    "action": "threads.page",
                    "gmail_client_mode": "fake",
                    "fake_threads": fake_threads,
                    "force_remote": True,
                    "query": "in:inbox -category:promotions -category:updates",
                    "required_label": "INBOX",
                    "excluded_labels": ["CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "SPAM", "TRASH"],
                    "limit": 2,
                },
            )["json"]
            second = self.run_backend(
                data_root,
                {
                    "action": "threads.page",
                    "gmail_client_mode": "fake",
                    "fake_threads": fake_threads,
                    "force_remote": True,
                    "query": "in:inbox -category:promotions -category:updates",
                    "required_label": "INBOX",
                    "excluded_labels": ["CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "SPAM", "TRASH"],
                    "limit": 2,
                    "page_token": first["next_page_token"],
                },
            )["json"]
            cached = self.run_backend(
                data_root,
                {
                    "action": "threads.page",
                    "required_label": "INBOX",
                    "excluded_labels": ["CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "SPAM", "TRASH"],
                    "limit": 2,
                },
            )["json"]

            self.assertEqual([item["id"] for item in first["threads"]], ["thread_page_0", "thread_page_1"])
            self.assertEqual(first["next_page_token"], "2")
            self.assertEqual([item["id"] for item in second["threads"]], ["thread_page_2"])
            self.assertEqual(second["next_page_token"], "")
            self.assertEqual(cached["source"], "cache")
            self.assertEqual(len(cached["threads"]), 2)
            self.assertTrue(cached["has_more"])

    def test_gmail_payload_dates_use_message_internal_date_not_sync_time(self) -> None:
        thread = thread_from_gmail_payload(
            {
                "id": "thread_real_dates",
                "messages": [
                    {
                        "id": "msg_old",
                        "internalDate": "1713697200000",
                        "labelIds": ["INBOX"],
                        "snippet": "Older",
                        "payload": {
                            "headers": [
                                {"name": "From", "value": "old@example.com"},
                                {"name": "To", "value": "user@example.com"},
                                {"name": "Subject", "value": "Real date"},
                            ]
                        },
                    },
                    {
                        "id": "msg_new",
                        "internalDate": "1713783600000",
                        "labelIds": ["INBOX", "UNREAD"],
                        "snippet": "Newer",
                        "payload": {
                            "headers": [
                                {"name": "From", "value": "new@example.com"},
                                {"name": "To", "value": "user@example.com"},
                                {"name": "Subject", "value": "Real date"},
                            ]
                        },
                    },
                ],
            }
        )

        self.assertEqual(thread.messages[0].received_at, "2024-04-21T11:00:00Z")
        self.assertEqual(thread.messages[1].received_at, "2024-04-22T11:00:00Z")
        self.assertEqual(thread.updated_at, "2024-04-22T11:00:00Z")

    def test_send_requires_explicit_approval_and_consumes_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"

            rejected = self.run_backend(data_root, {"action": "send.approved", "gmail_client_mode": "fake"})
            approval = self.run_backend(
                data_root,
                {
                    "action": "send.request_approval",
                    "to_emails": ["mario.rossi@acme.example"],
                    "subject": "Re: Allineamento",
                    "body_text": "Confermo il follow-up.",
                    "confirmation_text": "invia questa email",
                },
            )["json"]["approval"]
            sent = self.run_backend(data_root, {"action": "send.approved", "approval_id": approval["id"], "gmail_client_mode": "fake"})["json"]
            second = self.run_backend(data_root, {"action": "send.approved", "approval_id": approval["id"], "gmail_client_mode": "fake"})

            self.assertEqual(rejected["status_code"], 400)
            self.assertEqual(sent["gmail"]["id"], "fake_msg_1")
            self.assertEqual(second["status_code"], 400)

    def test_send_approval_can_include_workspace_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace_root = Path(temp)
            data_root = workspace_root / "data" / "gmail-app"
            attachment_path = workspace_root / "storage" / "generated" / "brief.txt"
            attachment_path.parent.mkdir(parents=True)
            attachment_path.write_text("Attachment body", encoding="utf-8")

            approval = self.run_backend(
                data_root,
                {
                    "action": "send.request_approval",
                    "to_emails": ["mario.rossi@acme.example"],
                    "subject": "Brief",
                    "body_text": "In allegato.",
                    "workspace_attachments": ["storage/generated/brief.txt"],
                },
            )["json"]["approval"]
            sent = self.run_backend(data_root, {"action": "send.approved", "approval_id": approval["id"], "gmail_client_mode": "fake"})["json"]

            self.assertEqual(approval["attachments"][0]["workspace_relative_path"], "storage/generated/brief.txt")
            self.assertEqual(approval["attachments"][0]["filename"], "brief.txt")
            self.assertEqual(sent["gmail"]["attachments"], [{"filename": "brief.txt", "content_type": "text/plain", "size_bytes": 15}])

    def test_send_approval_rejects_attachments_outside_workspace_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"

            rejected = self.run_backend(
                data_root,
                {
                    "action": "send.request_approval",
                    "to_emails": ["mario.rossi@acme.example"],
                    "subject": "Brief",
                    "body_text": "In allegato.",
                    "workspace_attachments": ["data/crm/private.sqlite"],
                },
            )

            self.assertEqual(rejected["status_code"], 400)
            self.assertIn("storage/generated or storage/uploaded", rejected["json"]["detail"])

    def test_relationship_suggestion_can_be_marked_reviewed_without_cross_app_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"
            search = self.run_backend(data_root, {"action": "threads.search", "gmail_client_mode": "fake", "query": "CRM"})["json"]
            summary = self.run_backend(data_root, {"action": "threads.summarize", "thread_id": search["threads"][0]["id"]})["json"]
            suggestion = summary["suggestions"][0]

            reviewed = self.run_backend(
                data_root,
                {
                    "action": "suggestions.mark_reviewed",
                    "suggestion_id": suggestion["id"],
                    "decision": "reviewed",
                },
            )["json"]
            pending = self.run_backend(data_root, {"action": "suggestions.list"})["json"]["suggestions"]

            self.assertEqual(reviewed["decision"]["decision"], "reviewed")
            self.assertFalse(any(item["id"] == suggestion["id"] for item in pending))
            self.assertFalse((Path(temp) / "data" / "crm").exists())

    def test_gmail_references_expose_threads_and_messages_without_cross_app_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"
            self.run_backend(data_root, {"action": "threads.search", "gmail_client_mode": "fake", "query": "CRM"})

            manifest = self.run_backend(data_root, {"action": "references.manifest"})["json"]
            thread_search = self.run_backend(data_root, {"action": "references.search", "entity_type": "thread", "query": "CRM"})["json"]
            message_search = self.run_backend(data_root, {"action": "references.search", "entity_type": "message", "query": "follow-up"})["json"]
            resolved = self.run_backend(data_root, {"action": "references.resolve", "entity_type": "thread", "entity_id": "thread_demo_1"})["json"]
            summarized = self.run_backend(data_root, {"action": "references.summarize", "entity_type": "message", "entity_id": "msg_demo_1"})["json"]

            self.assertEqual({item["entity_type"] for item in manifest["entity_types"]}, {"thread", "message"})
            self.assertEqual(thread_search["results"][0]["app_id"], "gmail-app")
            self.assertEqual(thread_search["results"][0]["entity_type"], "thread")
            self.assertEqual(message_search["results"][0]["entity_type"], "message")
            self.assertTrue(resolved["exists"])
            self.assertEqual(resolved["entity_id"], "thread_demo_1")
            self.assertIn("follow-up commerciale", summarized["summary"])

    def test_backend_cli_and_mcp_share_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"
            backend = self.run_backend(data_root, {"action": "connection.status"})
            cli = run_json_entrypoint(
                GMAIL_APP_ROOT / "cli" / "app_cli.py",
                payload={"workspace_id": "default", "data_root": str(data_root), "arguments": {"command": "status"}},
                cwd=GMAIL_APP_ROOT,
            )
            mcp = run_json_entrypoint(
                GMAIL_APP_ROOT / "mcp" / "server.py",
                payload={"workspace_id": "default", "data_root": str(data_root), "tool_name": "gmail_app_connection_status", "arguments": {}},
                cwd=GMAIL_APP_ROOT,
            )

            self.assertEqual(backend["status_code"], 200)
            self.assertEqual(cli["status_code"], 200)
            self.assertEqual(mcp["status_code"], 200)
            self.assertEqual(cli["health"]["schema_version"], "1")

    def test_oauth_authorization_url_and_mock_exchange_store_account_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"
            auth = self.run_backend(
                data_root,
                {
                    "action": "oauth.authorization_url",
                    "client_id": "client-id",
                    "redirect_uri": "http://localhost/apps/gmail-app/",
                },
            )["json"]
            exchanged = self.run_backend(
                data_root,
                {
                    "action": "oauth.exchange",
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "redirect_uri": "http://localhost/apps/gmail-app/",
                    "code": "code",
                    "code_verifier": "verifier",
                    "mock_token": {"access_token": "access", "expires_in": 3600, "scope": "gmail", "token_type": "Bearer"},
                    "mock_email": "person@company.example",
                },
            )["json"]
            status = self.run_backend(data_root, {"action": "connection.status"})["json"]

            self.assertIn("accounts.google.com/o/oauth2", auth["authorization_url"])
            self.assertIn("gmail.readonly", auth["authorization_url"])
            self.assertTrue(auth["code_verifier"])
            self.assertTrue(auth["state"])
            self.assertEqual(exchanged["account"]["email"], "person@company.example")
            self.assertEqual(status["connected_accounts"][0]["email"], "person@company.example")

    def test_backend_oauth_exchange_requests_app_scoped_secret_without_leaking_raw_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"
            result = run_json_entrypoint(
                GMAIL_APP_ROOT / "backend" / "app_backend.py",
                payload={
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "oauth.exchange",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                        "redirect_uri": "http://localhost/apps/gmail-app/",
                        "code": "code",
                        "code_verifier": "verifier",
                        "mock_token": {
                            "access_token": "access-token",
                            "refresh_token": "refresh-token",
                            "expires_in": 3600,
                            "scope": "gmail",
                            "token_type": "Bearer",
                        },
                        "mock_email": "person@company.example",
                    },
                },
                cwd=GMAIL_APP_ROOT,
            )

            self.assertEqual(result["status_code"], 200)
            self.assertNotIn("refresh_token", result["json"]["token"])
            self.assertNotIn("token_secret", result["json"])
            self.assertEqual(result["platform_secret_writes"][0]["logical_name"], "gmail-oauth")
            self.assertEqual(result["platform_secret_writes"][0]["raw_value"]["refresh_token"], "refresh-token")

    def test_send_without_real_token_does_not_consume_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "gmail-app"
            approval = self.run_backend(
                data_root,
                {
                    "action": "send.request_approval",
                    "to_emails": ["person@example.com"],
                    "subject": "Hello",
                    "body_text": "Body",
                    "confirmation_text": "send",
                },
            )["json"]["approval"]

            rejected = self.run_backend(data_root, {"action": "send.approved", "approval_id": approval["id"]})
            sent = self.run_backend(data_root, {"action": "send.approved", "approval_id": approval["id"], "gmail_client_mode": "fake"})["json"]

            self.assertEqual(rejected["status_code"], 400)
            self.assertEqual(sent["gmail"]["id"], "fake_msg_1")

    def test_core_app_secret_write_and_resolution_are_app_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "secrets"
            state = SimpleNamespace(
                secret_store=MongoSecretStore(
                    SecretCollections(
                        secrets=JsonFileCollection(root / "secrets.json"),
                        values=JsonFileCollection(root / "values.json"),
                        bindings=JsonFileCollection(root / "bindings.json"),
                    )
                )
            )
            result = {
                "platform_secret_writes": [
                    {
                        "logical_name": "gmail-oauth",
                        "alias": "default-gmail-app-oauth",
                        "label": "Gmail OAuth",
                        "raw_value": {"refresh_token": "refresh-token"},
                    }
                ]
            }

            persisted = _apply_app_secret_writes(state, workspace_id="default", app_id="gmail-app", result=result)
            gmail_secrets = _resolve_app_secret_payload(state, workspace_id="default", app_id="gmail-app")
            other_app_secrets = _resolve_app_secret_payload(state, workspace_id="default", app_id="other-app")

            self.assertEqual(persisted[0]["logical_name"], "gmail-oauth")
            self.assertNotIn("platform_secret_writes", result)
            self.assertIn("refresh-token", gmail_secrets["gmail-oauth"])
            self.assertEqual(other_app_secrets, {})


if __name__ == "__main__":
    unittest.main()
