"""Mailbox unions, counts and unfiltered display pagination share one contract."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import quote

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))
from backend.database import connect, ensure_schema
from backend.pwa_read_model import read_model
from backend.providers.gmail import _cache_thread
from backend.store import count_threads, list_threads, mailbox_counts


class MailboxFiltersTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        ensure_schema(self.root)
        self.accounts = ("a", "user:alias, café@example.com")
        self.mailboxes = ("inbox", "sent", "drafts", "starred", "trash")
        self.rows = []
        with connect(self.root) as db:
            for account in self.accounts:
                db.execute(
                    """INSERT INTO connections(id, provider, email_address, display_name, status, created_at, updated_at)
                    VALUES (?, 'imap_smtp', ?, ?, 'connected', '2026-09-13', '2026-09-13')""",
                    (account, account, account),
                )
                for mailbox in self.mailboxes:
                    self.rows.append((f"{account}-{mailbox}", account, [mailbox]))
            self.rows.append(("overlap", "a", ["inbox", "sent", "starred"]))
            # Reverse insertion order: equal timestamps must still sort by id.
            for thread_id, account, labels in reversed(self.rows):
                db.execute(
                    """INSERT INTO threads(id, connection_id, provider_thread_id, subject,
                    last_message_at, snippet, unread, starred, labels_json, updated_at)
                    VALUES (?, ?, ?, ?, '2026-09-13T10:00:00Z', '', 1, ?, ?, '2026-09-13')""",
                    (thread_id, account, thread_id, thread_id, int("starred" in labels), json.dumps(labels)),
                )

    def test_every_mailbox_matches_exact_account_or_aggregate_with_consistent_counts(self):
        counts = mailbox_counts(self.root)
        for mailbox in self.mailboxes:
            for account in (None, *self.accounts):
                with self.subTest(mailbox=mailbox, account=account):
                    scope = f"connection:{quote(account, safe='')}:{mailbox}" if account else f"all:{mailbox}"
                    expected = sorted(row[0] for row in self.rows if mailbox in row[2] and (not account or row[1] == account))
                    payload = {"mailbox_scopes": scope, "mailbox": "ignored", "connection_id": "ignored"}
                    self.assertEqual([row["id"] for row in list_threads(self.root, payload)], expected)
                    self.assertEqual(count_threads(self.root, payload), len(expected))
                    if account:
                        self.assertEqual(counts[account][mailbox], {"total": len(expected), "unread": len(expected)})

    def test_union_deduplicates_overlapping_labels_and_intersects_search(self):
        scopes = "all:inbox,all:sent,connection:a:inbox,all:inbox"
        expected = sorted(row[0] for row in self.rows if "inbox" in row[2] or "sent" in row[2])
        self.assertEqual([row["id"] for row in list_threads(self.root, {"mailbox_scopes": scopes})], expected)
        self.assertEqual(count_threads(self.root, {"mailbox_scopes": scopes}), len(expected))
        self.assertEqual([row["id"] for row in list_threads(self.root, {"mailbox_scopes": scopes, "query": "overlap"})], ["overlap"])
        self.assertEqual(list_threads(self.root, {"mailbox_scopes": scopes, "query": "trash"}), [])

    def test_empty_and_invalid_scope_selections_never_fall_back_to_inbox(self):
        for scopes in ("", [], "bad,all:unknown,connection::sent"):
            with self.subTest(scopes=scopes):
                payload = {"mailbox_scopes": scopes, "mailbox": "inbox"}
                self.assertEqual(list_threads(self.root, payload), [])
                self.assertEqual(count_threads(self.root, payload), 0)

    def test_display_collection_spans_all_folders_and_pages_with_stable_ties(self):
        collected = []
        for offset in range(0, len(self.rows), 2):
            response = read_model(self.root, {"kind": "threads", "max_threads": 2, "offset": offset})
            page = response["payload"]["data"]
            self.assertEqual(page["total_count"], len(self.rows))
            self.assertEqual(page["offset"], offset)
            self.assertEqual(page["limit"], 2)
            collected.extend(item["id"] for item in page["items"])
        self.assertEqual(collected, sorted(row[0] for row in self.rows))

    def test_gmail_draft_label_matches_canonical_drafts_filter_and_counts(self):
        with connect(self.root) as db:
            db.execute("UPDATE connections SET provider = 'gmail' WHERE id = 'a'")
        _cache_thread(self.root, "a", {
            "id": "provider-draft", "messages": [{
                "id": "message-draft", "labelIds": ["DRAFT", "STARRED"], "internalDate": "1789293600000",
                "payload": {"mimeType": "text/plain", "headers": [{"name": "Subject", "value": "Provider draft"}], "body": {"data": "VGV4dA"}},
            }],
        })
        payload = {"mailbox_scopes": "connection:a:drafts", "query": "Provider draft"}
        items = list_threads(self.root, payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["labels"], ["drafts", "starred"])
        self.assertEqual(mailbox_counts(self.root)["a"]["drafts"]["total"], 2)

    def test_existing_gmail_draft_labels_are_migrated_idempotently_without_resync(self):
        with connect(self.root) as db:
            db.execute("UPDATE connections SET provider = 'gmail' WHERE id = 'a'")
            db.execute("UPDATE threads SET labels_json = ? WHERE subject = 'a-drafts'", ('["draft", "drafts", "starred"]',))
            db.execute("UPDATE schema_metadata SET value = '9' WHERE key = 'schema_version'")
        ensure_schema(self.root)
        ensure_schema(self.root)
        items = list_threads(self.root, {"mailbox_scopes": "connection:a:drafts"})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["labels"], ["drafts", "starred"])
        self.assertEqual(mailbox_counts(self.root)["a"]["drafts"]["total"], 1)
        with connect(self.root) as db:
            self.assertEqual(db.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()[0], "10")


if __name__ == "__main__":
    unittest.main()
