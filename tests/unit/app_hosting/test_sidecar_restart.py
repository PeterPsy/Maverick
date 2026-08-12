"""Tests for the generic workspace-app sidecar restart capability."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.apps.errors import AppLifecycleError
from core.apps.models import WorkspaceAppBindingRecord
from core.apps.sidecar_restart import restart_workspace_app_sidecars


class SidecarRestartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = WorkspaceAppBindingRecord(
            binding_id="binding-design",
            workspace_id="workspace-a",
            app_id="design-studio",
            source_record_id="source-design",
            source_kind="platform",
            status="enabled",
            active_version="1.0.0",
            data_root="/workspace-a/data/design-studio",
            installed_at="2026-08-12T00:00:00Z",
            updated_at="2026-08-12T00:00:00Z",
        )
        self.store = SimpleNamespace(get_workspace_app_binding=Mock(return_value=self.binding))
        self.sessions = SimpleNamespace(revoke_app=Mock())
        self.event_bus = SimpleNamespace(publish=Mock())
        self.sidecar = SimpleNamespace(service_id="opendesign")
        self.parsed = SimpleNamespace(
            contract=SimpleNamespace(services=SimpleNamespace(http_sidecars=[self.sidecar]))
        )

    def test_restart_is_scoped_revokes_app_sessions_and_emits_remount_event(self) -> None:
        readiness = {
            "ready": True,
            "service_count": 1,
            "stopped_service_count": 1,
            "services": [{"service_id": "opendesign", "instance_id": "opaque"}],
        }
        with (
            patch(
                "core.apps.sidecar_restart.resolve_workspace_app_surface",
                return_value=(Path("/repo/apps/design-studio"), self.parsed),
            ),
            patch(
                "core.apps.sidecar_restart.restart_declared_app_sidecars",
                return_value=readiness,
            ) as restart,
        ):
            result = restart_workspace_app_sidecars(
                self.store,
                workspace_id="workspace-a",
                app_id="design-studio",
                sidecar_browser_sessions=self.sessions,
                start_path=Path("/repo"),
                app_event_bus=self.event_bus,
            )

        self.sessions.revoke_app.assert_called_once_with(
            workspace_id="workspace-a",
            app_id="design-studio",
        )
        restart.assert_called_once()
        restart_kwargs = restart.call_args.kwargs
        self.assertEqual(restart_kwargs["workspace_id"], "workspace-a")
        self.assertEqual(restart_kwargs["app_id"], "design-studio")
        self.assertEqual(tuple(restart_kwargs["sidecars"]), (self.sidecar,))
        self.assertEqual(result["readiness"], readiness)
        event = self.event_bus.publish.call_args.args[0]
        self.assertEqual(event["type"], "maverick.app.runtime-changed")
        self.assertEqual(event["owner_app_id"], "design-studio")
        self.assertEqual(event["workspace_id"], "workspace-a")

    def test_restart_failure_audit_contains_only_error_class(self) -> None:
        audit = Mock()
        with (
            patch(
                "core.apps.sidecar_restart.resolve_workspace_app_surface",
                return_value=(Path("/repo/apps/design-studio"), self.parsed),
            ),
            patch(
                "core.apps.sidecar_restart.restart_declared_app_sidecars",
                side_effect=RuntimeError("failed at /private/token/path"),
            ),
            patch("core.apps.sidecar_restart.record_platform_audit", audit),
        ):
            with self.assertRaisesRegex(AppLifecycleError, "RuntimeError") as raised:
                restart_workspace_app_sidecars(
                    self.store,
                    workspace_id="workspace-a",
                    app_id="design-studio",
                    sidecar_browser_sessions=self.sessions,
                    start_path=Path("/repo"),
                    observability_store=object(),
                )

        self.assertNotIn("private/token", str(raised.exception))
        payload = audit.call_args.kwargs["payload"]
        self.assertEqual(payload["error_code"], "RuntimeError")
        self.assertNotIn("private/token", str(payload))

    def test_disabled_app_is_rejected_before_session_revocation(self) -> None:
        self.store.get_workspace_app_binding.return_value = SimpleNamespace(
            status="disabled",
        )
        with self.assertRaisesRegex(AppLifecycleError, "must be enabled"):
            restart_workspace_app_sidecars(
                self.store,
                workspace_id="workspace-a",
                app_id="design-studio",
                sidecar_browser_sessions=self.sessions,
                start_path=Path("/repo"),
            )
        self.sessions.revoke_app.assert_not_called()


if __name__ == "__main__":
    unittest.main()
