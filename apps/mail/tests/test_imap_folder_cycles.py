"""Continuation must finish both recent messages and flags in every folder."""

import test_sync_regressions as fixtures
from providers.imap_smtp import ImapSmtpProvider
from database import connect
from store import list_threads
import unittest


class FolderCycleTest(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.SyncRegressionTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root, self.secrets = fixture.root, fixture.secrets
        self.client = fixtures.FakeImap()
        original = self.client.uid
        self.starred_folder = None

        def uid(command, *args):
            result = original(command, *args)
            if command == "FETCH" and args[1] == "(UID FLAGS)":
                flags = r"\Seen \Flagged" if self.client.folder == self.starred_folder else r"\Seen"
                return "OK", [f"1 (UID {value} FLAGS ({flags}))".encode() for value in args[0].split(",")]
            if command == "FETCH":
                return "OK", [(b"1 (FLAGS (\\Seen))", result[1][0][1])]
            return result

        self.client.uid = uid
        self.provider = ImapSmtpProvider(imap_factory=lambda _: self.client)

    def sync(self, limit=25, continuation=False):
        return self.provider.sync_incremental(self.root, "imap_smtp", app_secrets=self.secrets,
                                              max_threads=limit, continue_cursor=continuation)

    def populate(self, count):
        self.client.folders = {"INBOX": {1}, **{f"Folder{i:02}": {1} for i in range(count - 1)}}
        result = self.sync()
        for _ in range(count * 2):
            if not result["has_more"]:
                break
            result = self.sync(15, True)
        self.assertFalse(result["has_more"])

    def test_pending_recent_messages_survive_a_continuation_in_other_folders(self):
        self.populate(11)
        self.client.folders["INBOX"].update(range(2, 202))
        result = self.sync()
        for _ in range(100):
            with connect(self.root) as db:
                cached = db.execute("SELECT COUNT(*) FROM messages WHERE provider_message_id LIKE 'INBOX:42:%'").fetchone()[0]
            if cached < 201:
                self.assertTrue(result["has_more"], f"Sync claimed completion with only {cached}/201 messages")
            if not result["has_more"]:
                break
            result = self.sync(15, True)
        self.assertEqual(cached, 201)
        self.assertFalse(result["has_more"])

    def test_completed_flag_sweeps_restart_in_continuation_only_folders(self):
        self.populate(20)
        self.starred_folder = "Folder18"
        head = self.sync()
        tail = self.sync(15, True)
        self.assertTrue(head["has_more"])
        self.assertFalse(tail["has_more"])
        target = next(thread for thread in list_threads(self.root, {"connection_id": "imap_smtp"})
                      if thread["subject"] == "Message Folder18-1")
        self.assertTrue(target["starred"])
        self.assertEqual(head["checked_flag_messages"] + tail["checked_flag_messages"], 20)
