from __future__ import annotations

from datetime import UTC, datetime
import json
import os
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
        (session_root / "session.json").write_text("{}\n", encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
