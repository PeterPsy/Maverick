from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from companion_store import database
from service import handle_action, mcp_result_for_tool
from website_scope import website_url


class BrowserInteractionTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.actor = {"workspace_id": "default", "user_id": "alice", "surface": "backend"}
        self.ref = "c-5394d8de-023e-4e63-acf3-cdc9d56e2aee-0"

    def call(self, action, **body):
        return handle_action(self.root, {"action": action, **body}, **self.actor)

    def connected(self, interactive=True):
        fields = {"access_mode": "interactive", "website_scope": "https", "agent_tab_id": str(uuid4())} if interactive else {}
        status, result = self.call("companion.connect", allowed_platforms=["instagram"], **fields)
        self.assertEqual(status, 201, result)
        credentials = {"session_id": result["connection"]["session_id"], "connector_secret": result["connector_secret"]}
        self.assertEqual(self.call("companion.poll", **credentials, url="https://www.instagram.com/")[0], 200)
        return credentials

    def test_https_navigation_preserves_routes_query_and_fragment(self):
        connection = self.connected()
        url = "https://owned-browser.example/settings?section=profile#edit"
        self.assertEqual(self.call("navigate", session_id=connection["session_id"], url=url)[0], 202)
        self.assertEqual(self.call("companion.poll", **connection, url=url)[0], 200)
        _, overview = self.call("companion.overview")
        self.assertEqual(overview["connections"][0]["website_scope"], "https")
        self.assertEqual(overview["connections"][0]["access_mode"], "interactive")
        self.assertEqual(overview["connections"][0]["url"], url)
        for forbidden in ["http://example.com/", "file:///etc/passwd", "chrome://settings", "https://localhost/", "https://127.0.0.1/", "https://2130706433/", "https://user:pass@example.com/"]:
            self.assertEqual(self.call("navigate", session_id=connection["session_id"], url=forbidden)[0], 400)

    def test_interactions_queue_on_mcp_surface_with_finite_arguments(self):
        connection = self.connected()
        for tool, action, arguments in [("browser_click", "click", {}), ("browser_type", "type", {"text": "Updated profile"}),
                                       ("browser_press_key", "press_key", {"key": "Enter"}), ("browser_hover", "hover", {}),
                                       ("browser_select_option", "select_option", {"values": ["enabled"]}),
                                       ("browser_set_checked", "set_checked", {"checked": True})]:
            status, operation = mcp_result_for_tool(self.root, tool, {"session_id": connection["session_id"], "ref": self.ref, **arguments},
                                                   workspace_id="default", user_id="alice", surface="mcp")
            self.assertEqual((status, operation["action"], operation["status"]), (202, action, "queued"))
        _, poll = self.call("companion.poll", **connection, url="https://www.instagram.com/")
        self.assertEqual(poll["command"]["parameters"], {"ref": self.ref})

    def test_read_only_connections_cannot_gain_interaction_or_https_scope(self):
        connection = self.connected(False)
        self.assertEqual(self.call("click", session_id=connection["session_id"], ref=self.ref)[0], 403)
        self.assertEqual(self.call("navigate", session_id=connection["session_id"], url="https://owned-browser.example/")[0], 400)
        self.assertEqual(self.call("companion.poll", **connection, url="https://owned-browser.example/")[0], 400)
        for fields in [{"access_mode": "interactive"}, {"website_scope": "https"},
                       {"access_mode": "interactive", "website_scope": "https"}]:
            self.assertEqual(self.call("companion.connect", allowed_platforms=["instagram"], **fields)[0], 400)
        self.assertEqual(self.call("companion.poll", **connection, url="https://www.instagram.com/", access_mode="interactive")[0], 400)

    def test_invalid_code_selectors_keys_and_oversized_input_never_queue(self):
        connection = self.connected()
        for action, arguments in [("click", {"ref": "#submit"}), ("click", {"ref": self.ref, "script": "document.cookie"}),
                                  ("type", {"ref": self.ref, "text": "a"*20001}), ("press_key", {"ref": self.ref, "key": "Control+V"}),
                                  ("set_checked", {"ref": self.ref, "checked": "true"}),
                                  ("select_option", {"ref": self.ref, "values": ["a"]*21})]:
            self.assertEqual(self.call(action, session_id=connection["session_id"], **arguments)[0], 400)
        with database(self.root) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM operations").fetchone()[0], 0)

    def test_target_fence_and_actor_isolation(self):
        connection = self.connected()
        self.assertEqual(self.call("click", session_id=connection["session_id"], ref=self.ref, target_url="https://owned-browser.example/")[0], 409)
        self.assertEqual(handle_action(self.root, {"action": "click", "session_id": connection["session_id"], "ref": self.ref},
                                       workspace_id="default", user_id="bob", surface="mcp")[0], 404)
        self.assertEqual(self.call("click", session_id=connection["session_id"], ref=self.ref, mode="interactive", target_url="https://www.instagram.com/")[0], 202)

    def test_url_normalization_keeps_https_website_semantics(self):
        self.assertEqual(website_url("https://EXAMPLE.com:443/settings?x=1#form"), "https://example.com/settings?x=1#form")
        self.assertEqual(website_url("https://example.com/a%2Fb?return=%2Fsettings"), "https://example.com/a%2Fb?return=%2Fsettings")

    def test_concurrent_polling_claims_only_once_and_keeps_durable_wal(self):
        connection = self.connected()
        self.call("click", session_id=connection["session_id"], ref=self.ref)
        with ThreadPoolExecutor(max_workers=6) as threads:
            results = list(threads.map(lambda _: self.call("companion.poll", **connection, url="https://www.instagram.com/"), range(12)))
        self.assertTrue(all(status == 200 for status, _ in results))
        self.assertEqual(sum(bool(result.get("command")) for _, result in results), 1)
        with database(self.root) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(db.execute("PRAGMA synchronous").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
