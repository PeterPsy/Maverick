"""Regression coverage for workspace background-hook fault isolation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.apps import runtime_event_hooks
from core.apps.errors import AppLifecycleError


class BackgroundHookDispatchTestCase(unittest.TestCase):
    def test_missing_app_source_does_not_block_healthy_app_hook(self) -> None:
        missing_binding = SimpleNamespace(
            app_id="video-studio",
            status="enabled",
            data_root="/workspaces/default/data/video-studio",
        )
        healthy_binding = SimpleNamespace(
            app_id="senses",
            status="enabled",
            data_root="/workspaces/default/data/senses",
        )
        parsed = SimpleNamespace(
            contract=SimpleNamespace(
                entrypoints=SimpleNamespace(
                    hooks={"background_tick": "hooks/background_tick.py"},
                    backend=None,
                ),
                capabilities=SimpleNamespace(data_events=[]),
            )
        )
        state = SimpleNamespace(app_store=object(), app_event_bus=None)

        def resolve_surface(_store, *, binding, start_path=None):
            if binding.app_id == "video-studio":
                raise AppLifecycleError("source root is missing")
            return Path("/apps/senses"), parsed

        paths = SimpleNamespace(
            root=Path("/workspaces/default"),
            uploaded_storage=Path("/workspaces/default/storage/uploaded"),
            generated_storage=Path("/workspaces/default/storage/generated"),
        )
        with (
            patch.object(
                runtime_event_hooks,
                "enabled_workspace_app_bindings",
                return_value=[missing_binding, healthy_binding],
            ),
            patch.object(runtime_event_hooks, "resolve_workspace_app_surface", side_effect=resolve_surface),
            patch.object(runtime_event_hooks, "workspace_paths", return_value=paths),
            patch.object(runtime_event_hooks, "_app_dependencies_payload", return_value={}),
            patch.object(runtime_event_hooks, "run_json_entrypoint", return_value={"ok": True}) as run_entrypoint,
            patch.object(runtime_event_hooks, "publish_declared_app_events"),
            patch.object(runtime_event_hooks, "_apply_runtime_requests"),
        ):
            results = runtime_event_hooks.dispatch_workspace_app_background_hooks(
                state,
                workspace_id="default",
                hook_name="background_tick",
                action="background.tick",
                start_path=Path("/repo"),
            )

        self.assertEqual(results, [{"app_id": "senses", "status": "completed", "result": {"ok": True}}])
        run_entrypoint.assert_called_once()


if __name__ == "__main__":
    unittest.main()
