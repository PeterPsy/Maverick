from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
import json
import os
import sqlite3
import unittest

from core.recovery.continuation_snapshot import snapshot_runtime_continuation_state
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 24, 14, 30, tzinfo=UTC)


class RuntimeContinuationSnapshotTest(unittest.TestCase):
    def test_snapshot_copies_only_scoped_mutable_records_privately(self) -> None:
        root = make_temp_repo_root(self)
        provider_root = root / "data" / "control-plane" / "json" / "providers"
        runtime_root = root / "workspaces" / "default" / "runtime"
        provider_root.mkdir(parents=True)
        (runtime_root / "sessions" / "session-1").mkdir(parents=True)
        (runtime_root / "sessions" / "session-2").mkdir(parents=True)
        (runtime_root / "sessions" / "session-1" / "events-history").mkdir()
        (provider_root / "profiles.json").write_text('{"revision": 7}\n', encoding="utf-8")
        (provider_root / "ignored.txt").write_text("not control-plane JSON\n", encoding="utf-8")
        (runtime_root / "threads.json").write_text("[]\n", encoding="utf-8")
        (runtime_root / "sessions" / "session-1" / "session.json").write_text(
            '{"session_id": "session-1"}\n',
            encoding="utf-8",
        )
        (runtime_root / "sessions" / "session-1" / "provider.log").write_text(
            "runtime evidence\n",
            encoding="utf-8",
        )
        (runtime_root / "sessions" / "session-1" / "events-history" / "000001.json").write_text(
            "[]\n",
            encoding="utf-8",
        )
        (runtime_root / "sessions" / "session-2" / "session.json").write_text(
            '{"session_id": "session-2"}\n',
            encoding="utf-8",
        )
        link = runtime_root / "sessions" / "session-1" / "latest.json"
        link.symlink_to("session.json")

        result = snapshot_runtime_continuation_state(
            root,
            workspace_id="default",
            session_ids={"session-1"},
            now=NOW,
        )

        snapshot_root = root / str(result["workspace_relative_path"])
        manifest = json.loads((snapshot_root / "manifest.json").read_text(encoding="utf-8"))
        copied_sources = {item["source"] for item in manifest["files"]}
        self.assertEqual(result["file_count"], 5)
        self.assertEqual(manifest["session_ids"], ["session-1"])
        self.assertIn("data/control-plane/json/providers/profiles.json", copied_sources)
        self.assertIn(
            "workspaces/default/runtime/sessions/session-1/events-history/000001.json",
            copied_sources,
        )
        self.assertNotIn("data/control-plane/json/providers/ignored.txt", copied_sources)
        self.assertNotIn(
            "workspaces/default/runtime/sessions/session-1/provider.log",
            copied_sources,
        )
        self.assertNotIn(
            "workspaces/default/runtime/sessions/session-2/session.json",
            copied_sources,
        )
        copied_link = snapshot_root / "workspace_runtime/sessions/session-1/latest.json"
        self.assertTrue(copied_link.is_symlink())
        self.assertEqual(os.readlink(copied_link), "session.json")
        self.assertEqual(snapshot_root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((snapshot_root / "manifest.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            (snapshot_root / "workspace_runtime/sessions/session-1/session.json").stat().st_mode
            & 0o777,
            0o600,
        )

    def test_snapshot_never_overwrites_an_existing_snapshot(self) -> None:
        root = make_temp_repo_root(self)
        provider_root = root / "data" / "control-plane" / "json" / "providers"
        provider_root.mkdir(parents=True)
        (provider_root / "profiles.json").write_text("{}\n", encoding="utf-8")
        session_root = root / "workspaces" / "default" / "runtime" / "sessions" / "session-1"
        session_root.mkdir(parents=True)
        (session_root / "session.json").write_text(
            '{"session_id": "session-1"}\n',
            encoding="utf-8",
        )
        snapshot_runtime_continuation_state(
            root,
            workspace_id="default",
            session_ids={"session-1"},
            now=NOW,
        )

        with self.assertRaises(FileExistsError):
            snapshot_runtime_continuation_state(
                root,
                workspace_id="default",
                session_ids={"session-1"},
                now=NOW,
            )

    def test_snapshot_includes_successor_from_pending_handoff(self) -> None:
        root = make_temp_repo_root(self)
        provider_root = root / "data" / "control-plane" / "json" / "providers"
        provider_root.mkdir(parents=True)
        (provider_root / "profiles.json").write_text("{}\n", encoding="utf-8")
        runtime_root = root / "workspaces" / "default" / "runtime"
        predecessor = runtime_root / "sessions" / "pending-predecessor"
        successor = runtime_root / "sessions" / "pending-successor"
        predecessor.mkdir(parents=True)
        successor.mkdir(parents=True)
        (predecessor / "session.json").write_text(
            json.dumps([{"session_id": "pending-predecessor"}]),
            encoding="utf-8",
        )
        (successor / "session.json").write_text(
            json.dumps(
                [
                    {
                        "session_id": "pending-successor",
                        "predecessor_session_id": "pending-predecessor",
                        "lineage_root_session_id": "pending-predecessor",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (runtime_root / "continuation_handoffs.json").write_text(
            json.dumps(
                [
                    {
                        "handoff_id": "pending-handoff",
                        "predecessor_session_id": "pending-predecessor",
                        "successor_session_id": "pending-successor",
                        "phase": "successor_prepared",
                    }
                ]
            ),
            encoding="utf-8",
        )

        result = snapshot_runtime_continuation_state(
            root,
            workspace_id="default",
            session_ids={"pending-predecessor"},
            now=NOW,
        )

        snapshot_root = root / str(result["workspace_relative_path"])
        manifest = json.loads(
            (snapshot_root / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["lineage_session_ids"],
            ["pending-predecessor", "pending-successor"],
        )
        copied_sources = {item["source"] for item in manifest["files"]}
        self.assertIn(
            "workspaces/default/runtime/sessions/pending-successor/session.json",
            copied_sources,
        )

    def test_snapshot_rejects_runtime_json_symlink_outside_scoped_source(self) -> None:
        root = make_temp_repo_root(self)
        provider_root = root / "data" / "control-plane" / "json" / "providers"
        provider_root.mkdir(parents=True)
        (provider_root / "profiles.json").write_text("{}\n", encoding="utf-8")
        session_root = (
            root / "workspaces" / "default" / "runtime" / "sessions" / "session-1"
        )
        session_root.mkdir(parents=True)
        (session_root / "session.json").write_text(
            '{"session_id": "session-1"}\n',
            encoding="utf-8",
        )
        outside = root / "outside-runtime-scope.json"
        outside.write_text('{"secret": true}\n', encoding="utf-8")
        (session_root / "leak.json").symlink_to(
            os.path.relpath(outside, start=session_root)
        )

        with self.assertRaisesRegex(RuntimeError, "snapshot_source_unsafe"):
            snapshot_runtime_continuation_state(
                root,
                workspace_id="default",
                session_ids={"session-1"},
                now=NOW,
            )

    def test_snapshot_backs_up_lineage_root_codex_database_and_rollout(self) -> None:
        root = make_temp_repo_root(self)
        provider_root = root / "data" / "control-plane" / "json" / "providers"
        provider_root.mkdir(parents=True)
        (provider_root / "profiles.json").write_text("{}\n", encoding="utf-8")
        sessions_root = root / "workspaces" / "default" / "runtime" / "sessions"
        lineage_root = sessions_root / "lineage-root"
        successor = sessions_root / "lineage-successor"
        lineage_root.mkdir(parents=True)
        successor.mkdir(parents=True)
        (lineage_root / "session.json").write_text(
            json.dumps(
                [
                    {
                        "session_id": "lineage-root",
                        "provider_id": "codex",
                        "execution_binding": {"runtime_engine_id": "codex"},
                        "continuation_successor_session_id": "lineage-successor",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (successor / "session.json").write_text(
            json.dumps(
                [
                    {
                        "session_id": "lineage-successor",
                        "provider_id": "codex",
                        "execution_binding": {"runtime_engine_id": "codex"},
                        "predecessor_session_id": "lineage-root",
                        "lineage_root_session_id": "lineage-root",
                    }
                ]
            ),
            encoding="utf-8",
        )
        codex_home = lineage_root / "codex-home"
        rollout = codex_home / "sessions" / "2026" / "08" / "rollout.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_text('{"event":"preserved"}\n', encoding="utf-8")
        database = codex_home / "state_5.sqlite"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO threads VALUES ('provider-thread')")
            connection.commit()

        result = snapshot_runtime_continuation_state(
            root,
            workspace_id="default",
            session_ids={"lineage-successor"},
            now=NOW,
        )

        snapshot_root = root / str(result["workspace_relative_path"])
        manifest = json.loads((snapshot_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["lineage_session_ids"],
            ["lineage-root", "lineage-successor"],
        )
        backed_up_home = (
            snapshot_root
            / "provider_conversation_homes"
            / "lineage-root"
            / "codex-home"
        )
        with closing(
            sqlite3.connect(backed_up_home / "state_5.sqlite")
        ) as connection:
            self.assertEqual(
                connection.execute("SELECT id FROM threads").fetchone(),
                ("provider-thread",),
            )
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone(), ("ok",))
        self.assertEqual(
            (backed_up_home / "sessions" / "2026" / "08" / "rollout.jsonl").read_text(
                encoding="utf-8"
            ),
            '{"event":"preserved"}\n',
        )
        kinds = {item.get("kind") for item in manifest["files"]}
        self.assertIn("sqlite_backup", kinds)
        self.assertIn("rollout", kinds)

    def test_snapshot_fails_closed_when_codex_conversation_home_is_missing(self) -> None:
        root = make_temp_repo_root(self)
        provider_root = root / "data" / "control-plane" / "json" / "providers"
        provider_root.mkdir(parents=True)
        (provider_root / "profiles.json").write_text("{}\n", encoding="utf-8")
        session_root = (
            root
            / "workspaces"
            / "default"
            / "runtime"
            / "sessions"
            / "missing-codex-home"
        )
        session_root.mkdir(parents=True)
        (session_root / "session.json").write_text(
            json.dumps(
                [
                    {
                        "session_id": "missing-codex-home",
                        "provider_id": "codex",
                        "execution_binding": {"runtime_engine_id": "codex"},
                    }
                ]
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RuntimeError, "provider_home_missing"):
            snapshot_runtime_continuation_state(
                root,
                workspace_id="default",
                session_ids={"missing-codex-home"},
                now=NOW,
            )

    def test_snapshot_requires_codex_database_and_rollout(self) -> None:
        for missing_kind in ("database", "rollout"):
            with self.subTest(missing_kind=missing_kind):
                root = make_temp_repo_root(self)
                provider_root = root / "data" / "control-plane" / "json" / "providers"
                provider_root.mkdir(parents=True)
                (provider_root / "profiles.json").write_text("{}\n", encoding="utf-8")
                session_root = (
                    root
                    / "workspaces"
                    / "default"
                    / "runtime"
                    / "sessions"
                    / f"missing-{missing_kind}"
                )
                session_root.mkdir(parents=True)
                (session_root / "session.json").write_text(
                    json.dumps(
                        [
                            {
                                "session_id": f"missing-{missing_kind}",
                                "provider_id": "codex",
                                "execution_binding": {"runtime_engine_id": "codex"},
                            }
                        ]
                    ),
                    encoding="utf-8",
                )
                codex_home = session_root / "codex-home"
                codex_home.mkdir()
                if missing_kind == "database":
                    rollout = codex_home / "sessions" / "rollout.jsonl"
                    rollout.parent.mkdir()
                    rollout.write_text("{}\n", encoding="utf-8")
                else:
                    with closing(sqlite3.connect(codex_home / "state_5.sqlite")) as connection:
                        connection.execute("CREATE TABLE threads (id TEXT)")
                        connection.commit()

                with self.assertRaisesRegex(RuntimeError, f"{missing_kind}_missing"):
                    snapshot_runtime_continuation_state(
                        root,
                        workspace_id="default",
                        session_ids={f"missing-{missing_kind}"},
                        now=NOW,
                    )


if __name__ == "__main__":
    unittest.main()
