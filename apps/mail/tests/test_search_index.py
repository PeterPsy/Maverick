"""Visible-text search, literal syntax and inexpensive schema guards."""

from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import database
from database import connect, ensure_schema, now_timestamp
from store import count_threads, list_threads, search_messages


class SearchIndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        ensure_schema(self.root)
        now = now_timestamp()
        with connect(self.root) as db:
            db.execute("INSERT INTO threads(id, connection_id, provider_thread_id, subject, last_message_at, snippet, labels_json, updated_at) VALUES ('thread', 'account', 'provider', 'Visible Subject', ?, 'Literal 25% discount_code', '[\"inbox\"]', ?)", (now, now))
            db.execute("INSERT INTO messages(id, thread_id, provider_message_id, sender_json, recipients_json, cc_json, sent_at, body_text, body_html_sanitized) VALUES ('message', 'thread', 'provider-message', '{\"email\":\"sender@example.com\",\"name\":\"Alice\"}', '[]', '[{\"email\":\"copy@example.com\"}]', ?, 'Visible body words', '<p class=\"markup-only\">Visible body words</p>')", (now,))
            db.execute("INSERT INTO attachments(id, message_id, provider_attachment_id, filename, created_at, updated_at) VALUES ('attachment', 'message', 'part', 'invoice.pdf', ?, ?)", (now, now))

    def test_search_indexes_visible_text_addresses_and_filenames(self):
        for query in ("visib", "body words", "sender@example.com", "copy@example.com", "alice", "invoice.pdf", "%", "_"):
            with self.subTest(query=query):
                self.assertEqual(count_threads(self.root, {"query": query}), 1)
        for query in ("markup-only", "email", "OR", "not-present%", '"invalid syntax'):
            with self.subTest(query=query):
                self.assertEqual(list_threads(self.root, {"query": query}), [])
        self.assertEqual(len(search_messages(self.root, "invoice.pdf")), 1)
        self.assertEqual(search_messages(self.root, "markup-only"), [])

    def test_punctuation_is_literal_not_a_wildcard(self):
        with connect(self.root) as db:
            db.execute("UPDATE threads SET snippet='No punctuation' WHERE id='thread'")
        self.assertEqual(list_threads(self.root, {"query": "%"}), [])
        self.assertEqual(list_threads(self.root, {"query": "_"}), [])

    def test_indexes_follow_message_attachment_and_label_changes(self):
        with connect(self.root) as db:
            db.execute("UPDATE attachments SET filename='renamed.txt' WHERE id='attachment'")
            db.execute("UPDATE threads SET labels_json='[\"sent\"]' WHERE id='thread'")
        self.assertEqual(count_threads(self.root, {"query": "invoice"}), 0)
        self.assertEqual(count_threads(self.root, {"query": "renamed"}), 1)
        self.assertEqual(count_threads(self.root, {"mailbox": "inbox"}), 0)
        self.assertEqual(count_threads(self.root, {"mailbox": "sent"}), 1)
        with connect(self.root) as db:
            db.execute("DELETE FROM attachments WHERE id='attachment'")
        self.assertEqual(count_threads(self.root, {"query": "renamed"}), 0)

    def test_current_schema_read_guard_performs_no_migration_or_write(self):
        statements = []
        @contextmanager
        def traced(root):
            with connect(root) as db:
                db.set_trace_callback(statements.append)
                yield db
        with patch.object(database, "connect", traced), patch.object(database, "_backfill_message_render_columns", side_effect=AssertionError("Migration repeated")):
            ensure_schema(self.root)
            list_threads(self.root, {})
            count_threads(self.root, {})
        self.assertTrue(statements)
        self.assertFalse(any(statement.lstrip().upper().startswith(("CREATE", "UPDATE", "DELETE", "INSERT", "ALTER")) for statement in statements))
        with connect(self.root) as db:
            plan = db.execute("EXPLAIN QUERY PLAN SELECT * FROM threads WHERE connection_id=? ORDER BY last_message_at DESC, id LIMIT 200", ("account",)).fetchall()
        self.assertTrue(any("idx_threads_connection_order" in row[3] for row in plan))
