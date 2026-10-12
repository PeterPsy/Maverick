from pathlib import Path
from contextlib import closing
import sqlite3
import sys
import time
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from companion_store import database
from service import handle_action


class AgentTabReconnectTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tab_id = str(uuid4())

    def call(self, action, *, user="alice", workspace="default", **body):
        return handle_action(self.root, {"action": action, **body},
                             workspace_id=workspace, user_id=user, surface="backend")

    def connect(self, tab_id=None, **actor):
        status, result = self.call("companion.connect", agent_tab_id=tab_id or self.tab_id,
                                   allowed_platforms=["instagram", "youtube"], **actor)
        self.assertEqual(status, 201, result)
        credentials = {"session_id": result["connection"]["session_id"],
                       "connector_secret": result["connector_secret"]}
        self.assertEqual(self.call("companion.poll", **credentials,
                                   url="https://www.instagram.com/", **actor)[0], 200)
        return credentials

    def test_reconnect_revokes_old_lease_and_cancels_its_pending_work(self):
        previous = self.connect()
        _, running = self.call("content.read", session_id=previous["session_id"])
        _, claimed = self.call("companion.poll", **previous, url="https://www.instagram.com/")
        _, queued = self.call("tabs", session_id=previous["session_id"])
        current = self.connect()
        _, overview = self.call("companion.overview")
        connections = {c["session_id"]: c for c in overview["connections"]}
        self.assertEqual(connections[previous["session_id"]]["status"], "revoked")
        self.assertEqual(connections[previous["session_id"]]["stop_reason"], "connection_replaced")
        self.assertEqual(connections[current["session_id"]]["status"], "connected")
        for operation in [running, queued]:
            self.assertEqual(self.call("operation.get", operation_id=operation["operation_id"])[1]["status"], "cancelled")
        self.assertEqual(self.call("companion.poll", **previous, url="https://www.instagram.com/")[0], 410)
        self.assertEqual(self.call("companion.complete", **previous, operation_id=running["operation_id"],
                                   lease_id=claimed["command"]["lease_id"], result={})[0], 410)
        self.call("companion.disconnect", session_id=current["session_id"])
        _, overview = self.call("companion.overview")
        self.assertFalse(any(c["status"] in {"connecting", "connected"} for c in overview["connections"]))

    def test_repeated_reconnects_do_not_exhaust_capacity(self):
        # Fill the other slots with independent agent tabs.
        others = [self.connect(str(uuid4())) for _ in range(3)]
        for _ in range(6):
            current = self.connect()
        _, overview = self.call("companion.overview")
        active = {c["session_id"] for c in overview["connections"] if c["status"] == "connected"}
        self.assertEqual(active, {current["session_id"], *(c["session_id"] for c in others)})

    def test_replacement_is_scoped_to_tab_actor_and_workspace(self):
        other_tab = self.connect(str(uuid4()))
        other_actor = self.connect(user="bob")
        other_workspace = self.connect(workspace="other")
        previous = self.connect()
        self.connect()
        self.assertEqual(self.call("companion.poll", **previous, url="https://www.instagram.com/")[0], 410)
        for credentials, actor in [(other_tab, {}), (other_actor, {"user": "bob"}),
                                   (other_workspace, {"workspace": "other"})]:
            self.assertEqual(self.call("companion.poll", **credentials, url="https://www.instagram.com/", **actor)[0], 200)

    def test_invalid_identity_cannot_revoke_a_connection(self):
        previous = self.connect()
        for value in ["", "not-a-uuid", True, {}, "5394D8DE-023E-4E63-ACF3-CDC9D56E2AEE"]:
            self.assertEqual(self.call("companion.connect", agent_tab_id=value, allowed_platforms=["instagram"])[0], 400)
        self.assertEqual(self.call("companion.connect", agent_tab_id=self.tab_id, allowed_platforms=[])[0], 400)
        self.assertEqual(self.call("companion.poll", **previous, url="https://www.instagram.com/")[0], 200)

    def test_schema_v2_upgrade_retains_existing_connections(self):
        with closing(sqlite3.connect(self.root / "companion.sqlite3")) as db:
            db.execute("""CREATE TABLE connections (
                session_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL,
                display_name TEXT NOT NULL, secret_hash TEXT NOT NULL, status TEXT NOT NULL,
                created_at REAL NOT NULL, seen_at REAL NOT NULL, expires_at REAL NOT NULL,
                tab_url TEXT NOT NULL DEFAULT '', tab_title TEXT NOT NULL DEFAULT '',
                allowed_platforms_json TEXT NOT NULL DEFAULT '[]', stop_reason TEXT NOT NULL DEFAULT ''
            )""")
            db.execute("PRAGMA user_version=2")
            db.execute("INSERT INTO connections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", ("chrome-existing", "default", "alice", "Agent", "hashed", "connected", time.time(), time.time(), time.time()+120, "", "Agent", '["instagram","youtube"]', ""))
            db.commit()
        with database(self.root) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertIn("agent_tab_id", {row["name"] for row in db.execute("PRAGMA table_info(connections)")})
            row = db.execute("SELECT * FROM connections WHERE session_id='chrome-existing'").fetchone()
            self.assertEqual(row["status"], "connected")
            self.assertEqual(row["allowed_platforms_json"], '["instagram","youtube"]')
            self.assertEqual(row["agent_tab_id"], "")


if __name__ == "__main__":
    unittest.main()
