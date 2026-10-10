"""Global IMAP work bounds, persistent flag progress and unchanged cache writes."""

import json
import imaplib
from pathlib import Path
import tempfile
import unittest

from test_sync_regressions import FakeImap, mime
from database import connect, ensure_schema, now_timestamp
from providers.imap_smtp import ImapSmtpProvider, _cache_message
from store import get_thread, list_threads


class ImapWorkBudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        ensure_schema(self.root)
        with connect(self.root) as db:
            db.execute("INSERT INTO connections(id, provider, email_address, display_name, status, settings_json, created_at, updated_at) VALUES ('imap', 'imap_smtp', 'me@example.com', 'Me', 'connected', '{\"username\":\"me@example.com\"}', ?, ?)", (now_timestamp(), now_timestamp()))
        _cache_message(self.root, "imap", {"name": "INBOX", "canonical": "inbox", "type": "inbox"}, 1, "42", mime("root"), flags={"\\Seen"})
        self.thread_id = list_threads(self.root, {"connection_id": "imap"})[0]["id"]
        with connect(self.root) as db:
            row = db.execute("SELECT * FROM messages").fetchone()
            db.executemany("INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, sent_at, body_text, labels_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           ((f"cached-{uid}", self.thread_id, f"INBOX:42:{uid}", row["sender_json"], row["recipients_json"], row["sent_at"], row["body_text"], row["labels_json"]) for uid in range(2, 402)))
            cursor = {"version": 2, "folders": {"INBOX": {"uidvalidity": "42", "last_uid": 401, "backfill_before": 1, "history_complete": True}}}
            db.execute("INSERT INTO sync_state(connection_id, cursor) VALUES ('imap', ?)", (json.dumps(cursor),))
            db.executescript("""CREATE TABLE search_writes (id INTEGER);
            CREATE TRIGGER count_search_writes AFTER INSERT ON mail_search BEGIN
            INSERT INTO search_writes VALUES (1); END;""")
        self.client = FakeImap()
        self.client.folders = {"INBOX": set(range(1, 402))}
        self.provider = ImapSmtpProvider(imap_factory=lambda _: self.client)

    def sync(self, limit, **kwargs):
        self.client.calls.clear()
        result = self.provider.sync_incremental(self.root, "imap", max_threads=limit, app_secrets={"mailbox-password": "fake"}, **kwargs)
        fetches = [args for _, command, args in self.client.calls if command == "FETCH"]
        units = sum(len(args[0].split(",")) for args in fetches)
        self.assertLessEqual(units, limit)
        self.assertEqual(units, result["work_units"])
        return result, fetches

    def test_one_message_budget_does_not_refresh_401_cached_uids(self):
        self.client.folders["INBOX"].add(402)
        first, fetches = self.sync(1)
        self.assertEqual(first["synced_messages"], 1)
        self.assertEqual(len(fetches), 1)
        self.assertTrue(first["has_more"])
        with connect(self.root) as db:
            db.execute("DELETE FROM search_writes")
        second, fetches = self.sync(1, continue_cursor=True)
        self.assertEqual(second["checked_flag_messages"], 1)
        self.assertEqual(fetches[0][0], "1")
        with connect(self.root) as db:
            cursor = json.loads(db.execute("SELECT cursor FROM sync_state WHERE connection_id='imap'").fetchone()[0])
            self.assertEqual(cursor["folders"]["INBOX"]["flags"]["after_uid"], 1)
        visited = [1]
        for _ in range(2):
            result, fetches = self.sync(200, continue_cursor=True)
            visited.extend(int(uid) for args in fetches for uid in args[0].split(","))
        self.assertEqual(visited, list(range(1, 402)))
        self.assertFalse(result["has_more"])
        with connect(self.root) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM search_writes").fetchone()[0], 0)

    def test_flag_changes_on_later_pages_are_eventually_aggregated(self):
        original = self.client.uid
        def flags(command, *args):
            if command == "FETCH" and args[1] == "(UID FLAGS)":
                self.client.calls.append((self.client.folder, command, args))
                responses = []
                for uid in args[0].split(","):
                    flags = r"\Seen \Flagged" if uid == "350" else r"\Seen"
                    responses.append(f"1 (FLAGS ({flags}) UID {uid})".encode())
                return "OK", responses
            return original(command, *args)
        self.client.uid = flags
        first, _ = self.sync(200)
        self.assertTrue(first["has_more"])
        self.assertFalse(get_thread(self.root, self.thread_id)["starred"])
        self.sync(200, continue_cursor=True)
        self.assertTrue(get_thread(self.root, self.thread_id)["starred"])
        final, _ = self.sync(200, continue_cursor=True)
        self.assertFalse(final["has_more"])

    def test_failed_flag_page_preserves_cursor_for_retry(self):
        with connect(self.root) as db:
            before = db.execute("SELECT cursor FROM sync_state WHERE connection_id='imap'").fetchone()[0]
        original = self.client.uid
        self.client.uid = lambda command, *args: ("NO", []) if command == "FETCH" else original(command, *args)
        with self.assertRaisesRegex(ValueError, "flag refresh failed"):
            self.sync(1)
        with connect(self.root) as db:
            self.assertEqual(db.execute("SELECT cursor FROM sync_state WHERE connection_id='imap'").fetchone()[0], before)
        self.client.uid = original
        result, fetches = self.sync(1)
        self.assertEqual(result["checked_flag_messages"], 1)
        self.assertEqual(fetches[0][0], "1")

    def test_nonpersisting_continuation_preserves_nested_flag_cursor(self):
        self.sync(1)
        with connect(self.root) as db:
            before = db.execute("SELECT cursor FROM sync_state WHERE connection_id='imap'").fetchone()[0]
        _, fetches = self.sync(1, continue_cursor=True, persist_cursor=False)
        self.assertEqual(fetches[0][0], "2")
        with connect(self.root) as db:
            self.assertEqual(db.execute("SELECT cursor FROM sync_state WHERE connection_id='imap'").fetchone()[0], before)
        _, fetches = self.sync(1, continue_cursor=True)
        self.assertEqual(fetches[0][0], "2")

    def test_many_folders_do_not_trigger_unbounded_inventory_requests(self):
        self.client.folders = {"INBOX": set(range(1, 402)), **{f"Folder{index}": set() for index in range(20)}}
        for index in range(3):
            result, _ = self.sync(1, continue_cursor=True)
            self.assertTrue(result["has_more"])
            searched = {folder for folder, command, _ in self.client.calls if command == "SEARCH"}
            self.assertEqual(searched, [{"INBOX"}, {"Folder0"}, {"Folder1"}][index])
            self.assertLessEqual(sum(command == "SEARCH" for _, command, _ in self.client.calls), 2)

    def test_reconnect_keeps_the_same_global_work_budget(self):
        self.client.folders["INBOX"].add(402)
        original = self.client.uid
        failed = False
        def transient(command, *args):
            nonlocal failed
            if command == "FETCH" and not failed:
                failed = True
                self.client.calls.append((self.client.folder, command, args))
                raise imaplib.IMAP4.abort("Transient read failure")
            return original(command, *args)
        self.client.uid = transient
        result, fetches = self.sync(2)
        self.assertEqual(len(fetches), 2)
        self.assertEqual(result["work_units"], 2)
        self.assertEqual(result["synced_messages"], 1)
