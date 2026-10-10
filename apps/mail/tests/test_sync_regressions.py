"""Backfill, provider deletion, flag aggregation and history expiry."""

from email.message import EmailMessage
from io import BytesIO
import imaplib
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from database import connect, ensure_schema, now_timestamp
from providers.gmail import GmailProvider, _cache_thread
from providers.imap_smtp import ImapSmtpProvider, _cache_message
from store import get_thread, list_threads


def gmail_thread(thread_id, messages=("one",), labels=("INBOX",)):
    return {"id": thread_id, "messages": [{"id": message_id, "labelIds": list(labels), "internalDate": "1710000000000", "payload": {"mimeType": "text/plain", "headers": [{"name": "Subject", "value": thread_id}], "body": {"data": "Qm9keQ"}}} for message_id in messages]}


def mime(uid, *, root=None):
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "me@example.com"
    message["Subject"] = f"Message {uid}"
    message["Message-ID"] = f"<{uid}@example.com>"
    message["Date"] = "Tue, 02 Jun 2026 12:00:00 +0000"
    if root:
        message["References"] = f"<{root}@example.com>"
        message["In-Reply-To"] = f"<{root}@example.com>"
    message.set_content("Body")
    return message.as_bytes()


class FakeImap:
    def __init__(self):
        self.folders = {"INBOX": set(range(1, 31)), "Sent": {1}}
        self.folder = "INBOX"
        self.validity = "42"
        self.debug = 0
        self.untagged_responses = {}
        self.calls = []
        self.message_version = ""

    def login(self, *args): return "OK", []
    def list(self): return "OK", [f'(\\HasNoChildren) "/" "{name}"'.encode() for name in self.folders]
    def select(self, folder, readonly=True):
        self.folder = folder.strip('"')
        self.untagged_responses["UIDVALIDITY"] = [self.validity.encode()] if self.validity else [None]
        return "OK", []
    response = imaplib.IMAP4.response
    _untagged_response = imaplib.IMAP4._untagged_response
    def logout(self): return "OK", []
    def uid(self, command, *args):
        self.calls.append((self.folder, command, args))
        if command == "SEARCH":
            ids = self.folders[self.folder]
            if args[1] == "UID":
                ids = {uid for uid in ids if uid >= int(args[2].split(":")[0])}
            return "OK", [" ".join(map(str, sorted(ids))).encode()]
        if args[1] == "(UID FLAGS)":
            return "OK", [f'1 (UID {uid} FLAGS (\\Seen))'.encode() for uid in args[0].split(",")]
        return "OK", [(b"1 (FLAGS ())", mime(f"{self.folder}-{args[0]}{self.message_version}"))]


class SyncRegressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        ensure_schema(self.root)
        with connect(self.root) as db:
            for provider in ("gmail", "imap_smtp"):
                db.execute("INSERT INTO connections(id, provider, email_address, display_name, status, settings_json, created_at, updated_at) VALUES (?, ?, 'me@example.com', 'Me', 'connected', ?, ?, ?)", (provider, provider, '{"username":"me@example.com"}', now_timestamp(), now_timestamp()))
        self.secrets = {"mailbox-password": "fake", "gmail-oauth-client-id": "fake", "gmail-oauth-client-secret": "fake", "gmail-refresh-token": "fake"}

    def test_uidvalidity_reset_replaces_reused_uids(self):
        client = FakeImap()
        client.folders = {"INBOX": {7}}
        provider = ImapSmtpProvider(imap_factory=lambda _: client)
        provider.sync_incremental(self.root, "imap_smtp", app_secrets=self.secrets, max_threads=1)
        old = list_threads(self.root, {"connection_id": "imap_smtp"})[0]
        client.validity, client.message_version = "99", "-replacement"
        provider.sync_incremental(self.root, "imap_smtp", app_secrets=self.secrets, max_threads=1)
        new = list_threads(self.root, {"connection_id": "imap_smtp"})
        self.assertEqual(len(new), 1)
        self.assertNotEqual(new[0]["id"], old["id"])
        self.assertIn("replacement", new[0]["subject"])
        self.assertEqual(get_thread(self.root, new[0]["id"])["messages"][0]["provider_message_id"], "INBOX:99:7")
        with self.assertRaises(ValueError):
            get_thread(self.root, old["id"])

    def test_missing_uidvalidity_preserves_cached_messages_and_cursor(self):
        client = FakeImap()
        client.folders = {"INBOX": {7}}
        provider = ImapSmtpProvider(imap_factory=lambda _: client)
        provider.sync_incremental(self.root, "imap_smtp", app_secrets=self.secrets, max_threads=1)
        with connect(self.root) as db:
            previous = db.execute("SELECT cursor FROM sync_state WHERE connection_id='imap_smtp'").fetchone()[0]
        client.validity = ""
        client.calls.clear()
        with self.assertRaisesRegex(ValueError, "UIDVALIDITY"):
            provider.sync_incremental(self.root, "imap_smtp", app_secrets=self.secrets, max_threads=1)
        self.assertFalse(client.calls)
        with connect(self.root) as db:
            self.assertEqual(db.execute("SELECT cursor FROM sync_state WHERE connection_id='imap_smtp'").fetchone()[0], previous)
            self.assertEqual(db.execute("SELECT provider_message_id FROM messages").fetchone()[0], "INBOX:42:7")

    def test_stale_uidvalidity_blocks_read_state_mutation(self):
        client = FakeImap()
        client.folders = {"INBOX": {7}}
        provider = ImapSmtpProvider(imap_factory=lambda _: client)
        provider.sync_incremental(self.root, "imap_smtp", app_secrets=self.secrets, max_threads=1)
        thread = list_threads(self.root, {"connection_id": "imap_smtp"})[0]
        client.validity = "99"
        client.calls.clear()
        with self.assertRaisesRegex(ValueError, "UIDVALIDITY"):
            provider.mark_read(self.root, thread["id"], app_secrets=self.secrets)
        self.assertFalse(any(command == "STORE" for _, command, _ in client.calls))
        self.assertTrue(get_thread(self.root, thread["id"])["unread"])

    def test_imap_backfill_visits_all_uids_and_folders_without_skips(self):
        client = FakeImap()
        provider = ImapSmtpProvider(imap_factory=lambda _: client)
        result = provider.sync_incremental(self.root, "imap_smtp", app_secrets=self.secrets, max_threads=10)
        self.assertTrue(result["has_more"])
        self.assertEqual(len(list_threads(self.root, {"mailbox": "sent"})), 1)
        for _ in range(4):
            if not result["has_more"]:
                break
            result = provider.sync_incremental(self.root, "imap_smtp", app_secrets=self.secrets, max_threads=10, continue_cursor=True)
        self.assertFalse(result["has_more"])
        self.assertEqual(len(list_threads(self.root, {"connection_id": "imap_smtp"})), 31)
        client.folders["INBOX"].remove(7)
        client.folders["INBOX"].add(31)
        provider.sync_incremental(self.root, "imap_smtp", app_secrets=self.secrets, max_threads=10)
        with connect(self.root) as db:
            ids = {row[0] for row in db.execute("SELECT provider_message_id FROM messages")}
        self.assertNotIn("INBOX:42:7", ids)
        self.assertIn("INBOX:42:31", ids)

    def test_sent_reply_preserves_inbox_and_unread_aggregate(self):
        _cache_message(self.root, "imap_smtp", {"name": "INBOX", "canonical": "inbox", "type": "inbox"}, 1, "42", mime("root"), flags=set())
        _cache_message(self.root, "imap_smtp", {"name": "Sent", "canonical": "sent", "type": "sent"}, 2, "42", mime("reply", root="root"), flags={"\\Seen"})
        threads = list_threads(self.root, {"connection_id": "imap_smtp"})
        self.assertEqual(len(threads), 1)
        self.assertTrue(threads[0]["unread"])
        self.assertIn("inbox", threads[0]["labels"])
        self.assertIn("sent", threads[0]["labels"])

    def test_imap_single_message_batches_rotate_folders(self):
        client = FakeImap()
        provider = ImapSmtpProvider(imap_factory=lambda _: client)
        for _ in range(2):
            provider.sync_incremental(self.root, "imap_smtp", app_secrets=self.secrets, max_threads=1, continue_cursor=True)
        self.assertEqual(len(list_threads(self.root, {"mailbox": "sent"})), 1)
        self.assertEqual(len(list_threads(self.root, {"connection_id": "imap_smtp"})), 2)

    def test_gmail_thread_payload_replaces_removed_messages_and_attachments(self):
        _cache_thread(self.root, "gmail", gmail_thread("thread", ("one", "two")))
        thread = list_threads(self.root, {"connection_id": "gmail"})[0]
        _cache_thread(self.root, "gmail", gmail_thread("thread", ("two",), ("SENT",)))
        fetched = get_thread(self.root, thread["id"])
        self.assertEqual([message["provider_message_id"] for message in fetched["messages"]], ["two"])
        self.assertEqual(fetched["labels"], ["sent"])
        _cache_thread(self.root, "gmail", {"id": "thread", "messages": []})
        self.assertEqual(list_threads(self.root, {"connection_id": "gmail"}), [])

    def test_gmail_history_updates_labels_and_deletes_gone_threads(self):
        _cache_thread(self.root, "gmail", gmail_thread("gone"))
        with connect(self.root) as db:
            db.execute("INSERT INTO sync_state(connection_id, cursor, provider_history_id) VALUES ('gmail', '{}', '100')")
        calls = []
        def transport(request):
            calls.append(request.full_url)
            path = urlparse(request.full_url).path
            if path.endswith("/token"): return {"access_token": "fake"}
            if path.endswith("/history"):
                self.assertEqual(parse_qs(urlparse(request.full_url).query)["startHistoryId"], ["100"])
                return {"historyId": "110", "history": [{"messagesDeleted": [{"message": {"id": "one", "threadId": "gone"}}]}]}
            if "/threads/gone" in path: raise HTTPError(request.full_url, 404, "gone", {}, BytesIO(b"{}"))
            if path.endswith("/threads"): return {"threads": []}
            raise AssertionError(path)
        result = GmailProvider(transport=transport).sync_incremental(self.root, "gmail", app_secrets=self.secrets, max_threads=10)
        self.assertFalse(result["has_more"])
        self.assertEqual(list_threads(self.root, {"connection_id": "gmail"}), [])
        with connect(self.root) as db:
            self.assertEqual(db.execute("SELECT provider_history_id FROM sync_state WHERE connection_id='gmail'").fetchone()[0], "110")

    def test_expired_gmail_history_reconciles_only_after_last_full_page(self):
        _cache_thread(self.root, "gmail", gmail_thread("stale"))
        with connect(self.root) as db:
            db.execute("INSERT INTO sync_state(connection_id, cursor, provider_history_id) VALUES ('gmail', '{}', '1')")
        def transport(request):
            path = urlparse(request.full_url).path
            if path.endswith("/token"): return {"access_token": "fake"}
            if path.endswith("/profile"): return {"historyId": "200"}
            if path.endswith("/history"): raise HTTPError(request.full_url, 404, "expired", {}, BytesIO(b"{}"))
            if path.endswith("/threads"):
                return {"threads": [{"id": "kept"}], "nextPageToken": "next"} if "pageToken" not in parse_qs(urlparse(request.full_url).query) else {"threads": []}
            if "/threads/kept" in path: return gmail_thread("kept", ("new",))
            raise AssertionError(path)
        provider = GmailProvider(transport=transport)
        first = provider.sync_incremental(self.root, "gmail", app_secrets=self.secrets, max_threads=1)
        self.assertTrue(first["has_more"])
        self.assertEqual(len(list_threads(self.root, {"connection_id": "gmail"})), 2)
        second = provider.sync_incremental(self.root, "gmail", app_secrets=self.secrets, max_threads=1, continue_cursor=True)
        self.assertFalse(second["has_more"])
        self.assertEqual([thread["subject"] for thread in list_threads(self.root, {"connection_id": "gmail"})], ["kept"])

    def test_gmail_pending_history_survives_bounded_continuations(self):
        with connect(self.root) as db:
            db.execute("INSERT INTO sync_state(connection_id, cursor, provider_history_id) VALUES ('gmail', '{}', '100')")
        history_calls = []
        def transport(request):
            path = urlparse(request.full_url).path
            if path.endswith("/token"): return {"access_token": "fake"}
            if path.endswith("/history"):
                history_calls.append(request.full_url)
                return {"historyId": "110", "history": [{"messagesAdded": [{"message": {"id": name, "threadId": name}} for name in ("a", "b", "c")]}]}
            if "/threads/" in path:
                name = path.rsplit("/", 1)[-1]
                return gmail_thread(name, (name,))
            if path.endswith("/threads"): return {"threads": []}
            raise AssertionError(path)
        provider = GmailProvider(transport=transport)
        for index in range(3):
            result = provider.sync_incremental(self.root, "gmail", app_secrets=self.secrets, max_threads=1, continue_cursor=True)
            self.assertEqual(result["synced_threads"], 1)
            with connect(self.root) as db:
                self.assertEqual(db.execute("SELECT provider_history_id FROM sync_state WHERE connection_id='gmail'").fetchone()[0], "110" if index == 2 else "100")
        self.assertEqual(len(history_calls), 1)
        self.assertEqual(len(list_threads(self.root, {"connection_id": "gmail"})), 3)
