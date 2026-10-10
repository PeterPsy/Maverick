"""Delivery state, concurrent sends and message-specific replies."""

from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.parser import BytesParser
from pathlib import Path
import base64
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock
from io import BytesIO
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from database import connect, ensure_schema, now_timestamp
from drafts import create_draft, get_draft, update_draft
from providers.gmail import GmailProvider, _cache_thread
from providers.imap_smtp import ImapSmtpProvider
from provider_errors import ProviderError
from store import get_thread, list_threads


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        ensure_schema(self.root)
        with connect(self.root) as db:
            for provider in ("gmail", "imap_smtp"):
                db.execute("INSERT INTO connections(id, provider, email_address, display_name, status, created_at, updated_at, settings_json) VALUES (?, ?, 'me@example.com', 'Me', 'connected', ?, ?, ?)", (provider, provider, now_timestamp(), now_timestamp(), json.dumps({"username": "me@example.com"})))
        self.secrets = {"gmail-oauth-client-id": "fake", "gmail-oauth-client-secret": "fake", "gmail-refresh-token": "fake", "mailbox-password": "fake"}
        self.requests = []
        def transport(request):
            if request.full_url.endswith("/token"):
                return {"access_token": "fake"}
            if request.full_url.endswith("/messages/send"):
                self.requests.append(request)
                return {"id": "accepted", "threadId": "new-thread"}
            raise RuntimeError("Simulated cache failure")
        self.gmail = GmailProvider(transport=transport)

    def draft(self, connection="gmail", **kwargs):
        return create_draft(self.root, {"connection_id": connection, "to": [{"email": "friend@example.com"}], "subject": "Subject", "body_text": "Body", **kwargs})

    def send(self, provider, draft):
        preview = provider.send_draft(self.root, draft["id"])
        return provider.send_draft(self.root, draft["id"], confirm=True, confirmation_token=preview["confirmation_preview"]["confirmation_token"], app_secrets=self.secrets)

    def test_accepted_gmail_send_survives_cache_failure_and_cannot_repeat(self):
        draft = self.draft()
        result = self.send(self.gmail, draft)
        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["sent"])
        self.assertIn("cache_refresh_failed", result["local_warnings"])
        self.assertEqual(get_draft(self.root, draft["id"])["send_result"]["provider_message_id"], "accepted")
        with self.assertRaises(ValueError):
            self.gmail.send_draft(self.root, draft["id"])
        self.assertEqual(len(self.requests), 1)

    def test_concurrent_approved_sends_only_submit_once(self):
        draft = self.draft()
        self.gmail.send_draft(self.root, draft["id"])
        def send():
            try:
                return self.gmail.send_draft(self.root, draft["id"], confirm=True, use_latest_confirmation=True, app_secrets=self.secrets)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: send(), range(2)))
        self.assertEqual(sum(bool(item and item["sent"]) for item in results), 1)
        self.assertEqual(len(self.requests), 1)

    def test_smtp_partial_and_unknown_delivery_block_retries(self):
        for behavior, expected in [({"reject@example.com": (550, b"rejected")}, "partially_sent"), (TimeoutError(), "unknown")]:
            with self.subTest(expected=expected):
                smtp = Mock()
                smtp.send_message.side_effect = behavior if isinstance(behavior, Exception) else None
                smtp.send_message.return_value = behavior
                provider = ImapSmtpProvider(smtp_factory=lambda _: smtp, imap_factory=lambda _: Mock())
                draft = self.draft("imap_smtp", to=[{"email": "friend@example.com"}, {"email": "reject@example.com"}])
                result = self.send(provider, draft)
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["sent"])
                if expected == "partially_sent":
                    self.assertEqual(result["accepted_recipients"], ["friend@example.com"])
                    self.assertEqual(result["refused_recipients"]["reject@example.com"]["smtp_code"], 550)
                with self.assertRaises(ValueError):
                    provider.send_draft(self.root, draft["id"])
                with self.assertRaises(ValueError):
                    update_draft(self.root, draft["id"], {"body_text": "Retry"})

    def test_edit_race_does_not_consume_approval_or_send(self):
        draft = self.draft()
        preview = self.gmail.send_draft(self.root, draft["id"])["confirmation_preview"]
        update_draft(self.root, draft["id"], {"body_text": "Changed"})
        with self.assertRaises(ValueError):
            self.gmail.send_draft(self.root, draft["id"], confirm=True, confirmation_token=preview["confirmation_token"], app_secrets=self.secrets)
        self.assertEqual(get_draft(self.root, draft["id"])["status"], "draft")
        self.assertEqual(self.requests, [])

    def test_reply_and_reply_all_respect_selected_message(self):
        _cache_thread(self.root, "gmail", {"id": "thread", "messages": [{"id": "message", "labelIds": ["INBOX"], "internalDate": "1710000000000", "payload": {"mimeType": "text/plain", "headers": [
            {"name": name, "value": value} for name, value in {"Subject": "Subject", "From": "author@example.com", "Reply-To": "reply@example.com", "To": "me@example.com, other@example.com", "Cc": "third@example.com", "Message-ID": "<selected@example.com>", "References": "<root@example.com>"}.items()
        ], "body": {"data": "Qm9keQ"}}}]})
        thread = list_threads(self.root, {"connection_id": "gmail"})[0]
        selected = get_thread(self.root, thread["id"])["messages"][0]["id"]
        with connect(self.root) as db:
            db.execute("UPDATE messages SET headers_json=? WHERE id=?", (json.dumps({"Message-ID": "<selected@example.com>", "Reply-To": "reply@example.com", "References": "<root@example.com>"}), selected))
            db.execute("INSERT INTO messages(id, thread_id, provider_message_id, sender_json, sent_at, headers_json) VALUES ('other-message', ?, 'other', '{\"email\":\"unrelated@example.com\"}', '2026-10-10T12:00:00Z', '{\"message-id\":\"<unrelated@example.com>\"}')", (thread["id"],))
        single = self.draft(thread_id=thread["id"], reply_message_id=selected, to=[])
        self.assertEqual(single["to"], [{"email": "reply@example.com"}])
        self.assertEqual(single["cc"], [])
        all_draft = self.draft(thread_id=thread["id"], reply_message_id=selected, to=[], reply_mode="reply_all")
        self.assertEqual({item["email"] for item in all_draft["cc"]}, {"other@example.com", "third@example.com"})
        result = self.send(self.gmail, single)
        self.assertTrue(result["sent"])
        raw = json.loads(self.requests[0].data)["raw"]
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        self.assertEqual(message["In-Reply-To"], "<selected@example.com>")
        self.assertEqual(message["References"], "<root@example.com> <selected@example.com>")
        with self.assertRaisesRegex(ValueError, "different mail connection"):
            self.draft("imap_smtp", thread_id=thread["id"])

    def test_reply_without_message_id_requires_refresh(self):
        _cache_thread(self.root, "gmail", {"id": "thread", "messages": [{"id": "message", "payload": {"headers": [{"name": "From", "value": "sender@example.com"}]}}]})
        thread = list_threads(self.root, {"connection_id": "gmail"})[0]
        with self.assertRaisesRegex(ValueError, "Message-ID"):
            self.draft(thread_id=thread["id"])

    def test_legacy_reply_without_headers_cannot_be_previewed_or_sent(self):
        for provider, connection in [(self.gmail, "gmail"), (ImapSmtpProvider(), "imap_smtp")]:
            draft = self.draft(connection)
            with connect(self.root) as db:
                db.execute("UPDATE drafts SET thread_id='legacy-thread' WHERE id=?", (draft["id"],))
            with self.assertRaisesRegex(ValueError, "Reply metadata is missing"):
                provider.send_draft(self.root, draft["id"])
            self.assertEqual(get_draft(self.root, draft["id"])["status"], "draft")

    def test_smtp_mime_has_conversation_headers(self):
        smtp = Mock()
        smtp.send_message.return_value = {}
        provider = ImapSmtpProvider(smtp_factory=lambda _: smtp, imap_factory=lambda _: Mock())
        draft = self.draft("imap_smtp")
        with connect(self.root) as db:
            db.execute("UPDATE drafts SET in_reply_to='<parent@example.com>', references_json='[\"<root@example.com>\", \"<parent@example.com>\"]' WHERE id=?", (draft["id"],))
        self.assertTrue(self.send(provider, draft)["sent"])
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["In-Reply-To"], "<parent@example.com>")
        self.assertEqual(message["References"], "<root@example.com> <parent@example.com>")

    def test_only_transient_reads_are_retried(self):
        calls = []
        def transport(request):
            calls.append(request.get_method())
            if len(calls) < 3 or request.get_method() == "POST":
                raise HTTPError(request.full_url, 503, "temporary", {}, BytesIO(b"{}"))
            return {"id": "read"}
        provider = GmailProvider(transport=transport)
        self.assertEqual(provider._gmail_json("GET", "threads/read", access_token="fake")["id"], "read")
        self.assertEqual(calls, ["GET", "GET", "GET"])
        with self.assertRaises(ProviderError) as raised:
            provider._gmail_json("POST", "messages/send", access_token="fake", payload={})
        self.assertFalse(raised.exception.delivery_rejected)
        self.assertEqual(calls[-1:], ["POST"])
        self.assertEqual(len(calls), 4)
