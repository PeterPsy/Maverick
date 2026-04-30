from __future__ import annotations

from dataclasses import dataclass
import unittest
from unittest.mock import patch

from core.api.background_hooks import run_background_hook_tick


@dataclass(frozen=True)
class Workspace:
    workspace_id: str
    status: str = "active"


class WorkspaceStore:
    def list_workspaces(self) -> list[Workspace]:
        return [Workspace("default"), Workspace("archived", status="archived")]


@dataclass(frozen=True)
class State:
    workspace_store: WorkspaceStore
    repository_root: str = "/repo"


class BackgroundHookSchedulerTest(unittest.TestCase):
    def test_tick_dispatches_declared_background_hook_for_active_workspaces(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_dispatch(*args, **kwargs):
            calls.append(kwargs)
            return [{"app_id": "fleet", "status": "completed"}]

        with patch("core.api.background_hooks.dispatch_workspace_app_background_hooks", side_effect=fake_dispatch):
            result = run_background_hook_tick(State(workspace_store=WorkspaceStore()))

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["workspace_id"], "default")
        self.assertEqual(calls[0]["hook_name"], "background_tick")
        self.assertEqual(calls[0]["action"], "background.tick")
        self.assertEqual(result["workspaces"][0]["workspace_id"], "default")


if __name__ == "__main__":
    unittest.main()
