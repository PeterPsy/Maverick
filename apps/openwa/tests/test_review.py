"""Transport recovery and actor-isolated notification retention regressions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from gateway import Gateway, GatewayError
from state import database, notify, notifications


class ReviewTests(unittest.TestCase):
    def test_non_json_errors_preserve_http_status_without_echoing_the_body(self):
        for status in (401, 403, 409, 429, 503):
            with self.subTest(status=status):
                response = MagicMock(status=status)
                response.read.return_value = b"<h1>private-provider-payload</h1>"
                connection = MagicMock()
                connection.getresponse.return_value = response
                with patch("gateway._connection", return_value=connection), self.assertRaises(GatewayError) as error:
                    Gateway("https://example.com", "test-key").request("POST", "/sessions/one/messages/send-text")
                self.assertEqual(error.exception.status, status)
                self.assertNotIn("private-provider-payload", str(error.exception))
                self.assertEqual(error.exception.uncertain_send, status in (409, 503))
                connection.close.assert_called_once()

    def test_empty_no_content_success_is_not_reported_as_a_provider_failure(self):
        response = MagicMock(status=204)
        response.read.return_value = b""
        connection = MagicMock()
        connection.getresponse.return_value = response
        with patch("gateway._connection", return_value=connection):
            result = Gateway("https://example.com", "test-key").request("POST", "/sessions/one/stop", {})
        self.assertIsNone(result)
        connection.close.assert_called_once()

    def test_invalid_success_still_fails_and_releases_the_connection(self):
        response = MagicMock(status=200)
        response.read.return_value = b"not-json"
        connection = MagicMock()
        connection.getresponse.return_value = response
        with patch("gateway._connection", return_value=connection), self.assertRaises(GatewayError):
            Gateway("https://example.com", "test-key").request("GET", "/sessions")
        connection.close.assert_called_once()

    def test_retention_is_bounded_per_actor_and_keeps_other_actors_notices(self):
        with tempfile.TemporaryDirectory() as root:
            notify(root, "alice", "important", "Check send", "Alice's unresolved send", "one")
            with database(root) as db:
                db.executemany("INSERT INTO notifications(id,user_id,title,body,session_id,created_at) VALUES (?,?,?,?,?,?)",
                               [(f"bob-{i}", "bob", "Notice", "", "two", f"2025-12-01T00:00:{i:04}") for i in range(1000)])
            notify(root, "bob", "latest", "Check send", "Bob's unresolved send", "two")
            self.assertEqual(notifications(root, "alice", 0, 50)["total"], 1)
            self.assertEqual(notifications(root, "bob", 0, 50)["total"], 1000)
            self.assertEqual(notifications(root, "bob", 0, 1)["notifications"][0]["body"], "Bob's unresolved send")
            with database(root) as db:
                plan = db.execute("EXPLAIN QUERY PLAN SELECT * FROM notifications WHERE user_id=? AND dismissed=0 ORDER BY created_at DESC LIMIT 50", ("alice",)).fetchall()
            self.assertIn("USING INDEX", json.dumps([tuple(row) for row in plan]))


if __name__ == "__main__":
    unittest.main()
