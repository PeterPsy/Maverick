"""Backend-owned runtime-session root purge worker tests."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.api.runtime_session_root_purge import run_runtime_session_root_purge_tick
from core.runtime.paths import runtime_session_root
from core.runtime.session_root_cleanup import stage_runtime_session_root_deletion
from tests.support.repo import make_temp_repo_root


class RuntimeSessionRootPurgeTest(unittest.TestCase):
    def test_tick_purges_only_the_configured_number_of_staged_roots(self) -> None:
        repo_root = make_temp_repo_root(self)
        for session_id in ("session-1", "session-2"):
            root = runtime_session_root("default", session_id, start_path=repo_root)
            root.mkdir(parents=True)
            stage_runtime_session_root_deletion(
                root,
                workspace_id="default",
                session_id=session_id,
                start_path=repo_root,
            )
        state = SimpleNamespace(
            repository_root=repo_root,
            workspace_store=SimpleNamespace(
                list_workspaces=lambda: [SimpleNamespace(workspace_id="default")],
            ),
        )

        first = run_runtime_session_root_purge_tick(state, max_roots=1)
        second = run_runtime_session_root_purge_tick(state, max_roots=1)

        self.assertEqual((first["attempted"], first["purged"], first["remaining"]), (1, 1, 1))
        self.assertTrue(first["reached_limit"])
        self.assertEqual((second["attempted"], second["purged"], second["remaining"]), (1, 1, 0))
        self.assertEqual(first["failures"], [])
        self.assertEqual(second["failures"], [])


if __name__ == "__main__":
    unittest.main()
