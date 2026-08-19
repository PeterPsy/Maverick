from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.runtime_cleanup_hooks import cleanup_app_runtime_session_metadata


class RuntimeCleanupHooksTest(unittest.TestCase):
    def test_cleanup_invokes_each_eligible_app_once_for_the_session_batch(self) -> None:
        bindings = [
            SimpleNamespace(app_id="design-studio", status="enabled"),
            SimpleNamespace(app_id="disabled-app", status="disabled"),
        ]
        state = SimpleNamespace(
            app_store=SimpleNamespace(list_workspace_app_bindings=lambda _workspace_id: bindings)
        )
        parsed = SimpleNamespace(
            contract=SimpleNamespace(
                permissions=SimpleNamespace(
                    runtime=SimpleNamespace(receive_cleanup_callbacks=True)
                ),
                entrypoints=SimpleNamespace(backend="backend/app_backend.py"),
            )
        )

        with patch(
            "core.api.app_registry.resolve_app_surface",
            return_value=(bindings[0], object(), parsed),
        ), patch(
            "core.api.runtime_cleanup_hooks._invoke_runtime_cleanup_backend",
            return_value={"cleaned_runtime_session_ids": ["root", "child"]},
        ) as invoke:
            results = cleanup_app_runtime_session_metadata(
                state,
                workspace_id="default",
                session_ids=["root", "child", "root"],
                start_path="/repo",
            )

        invoke.assert_called_once_with(
            state,
            workspace_id="default",
            app_id="design-studio",
            session_ids=["root", "child"],
            start_path="/repo",
        )
        self.assertEqual(
            results,
            [
                {
                    "app_id": "design-studio",
                    "cleaned_runtime_session_ids": ["root", "child"],
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
