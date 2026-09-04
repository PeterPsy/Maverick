"""Runtime-session root staging and deferred purge tests."""

from __future__ import annotations

import os
import stat
import unittest

from core.runtime.paths import runtime_session_root
from core.runtime.session_root_cleanup import (
    RuntimeSessionRootCleanupError,
    purge_staged_runtime_roots,
    runtime_session_deletion_quarantine_root,
    stage_runtime_session_root_deletion,
)
from tests.support.repo import make_temp_repo_root


class RuntimeSessionRootCleanupTest(unittest.TestCase):
    def test_stage_hides_root_atomically_before_deferred_purge(self) -> None:
        repo_root = make_temp_repo_root(self)
        session_root = runtime_session_root("default", "session-1", start_path=repo_root)
        (session_root / "nested").mkdir(parents=True)
        (session_root / "nested" / "marker.txt").write_text("delete", encoding="utf-8")

        staged_root = stage_runtime_session_root_deletion(
            session_root,
            workspace_id="default",
            session_id="session-1",
            start_path=repo_root,
        )

        self.assertIsNotNone(staged_root)
        assert staged_root is not None
        self.assertFalse(session_root.exists())
        self.assertEqual((staged_root / "nested" / "marker.txt").read_text(encoding="utf-8"), "delete")
        self.assertEqual(
            stat.S_IMODE(
                runtime_session_deletion_quarantine_root(
                    "default",
                    start_path=repo_root,
                ).stat().st_mode
            ),
            0o700,
        )

        result = purge_staged_runtime_roots(
            workspace_id="default",
            start_path=repo_root,
            max_roots=1,
        )

        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["purged"], 1)
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["remaining"], 0)
        self.assertFalse(staged_root.exists())

    def test_purge_is_bounded_and_leaves_a_restart_safe_queue(self) -> None:
        repo_root = make_temp_repo_root(self)
        for session_id in ("session-1", "session-2"):
            session_root = runtime_session_root("default", session_id, start_path=repo_root)
            session_root.mkdir(parents=True)
            stage_runtime_session_root_deletion(
                session_root,
                workspace_id="default",
                session_id=session_id,
                start_path=repo_root,
            )

        first = purge_staged_runtime_roots(
            workspace_id="default",
            start_path=repo_root,
            max_roots=1,
        )
        second = purge_staged_runtime_roots(
            workspace_id="default",
            start_path=repo_root,
            max_roots=1,
        )

        self.assertEqual((first["purged"], first["remaining"]), (1, 1))
        self.assertEqual((second["purged"], second["remaining"]), (1, 0))

    def test_stage_rejects_a_symlink_in_place_of_the_session_root(self) -> None:
        repo_root = make_temp_repo_root(self)
        outside = repo_root / "outside"
        outside.mkdir()
        session_root = runtime_session_root("default", "session-1", start_path=repo_root)
        session_root.parent.mkdir(parents=True)
        os.symlink(outside, session_root, target_is_directory=True)

        with self.assertRaisesRegex(RuntimeSessionRootCleanupError, "runtime_session_root_unsafe"):
            stage_runtime_session_root_deletion(
                session_root,
                workspace_id="default",
                session_id="session-1",
                start_path=repo_root,
            )

        self.assertTrue(outside.exists())
        self.assertTrue(session_root.is_symlink())
        self.assertFalse(runtime_session_deletion_quarantine_root("default", start_path=repo_root).exists())


if __name__ == "__main__":
    unittest.main()
