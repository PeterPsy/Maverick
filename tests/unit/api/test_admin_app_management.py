"""Tests for workspace-app lifecycle sidecar cleanup."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.admin_app_management import handle_admin_app_management_api
from core.apps.models import WorkspaceAppBindingRecord, WorkspaceAppStatus


class AdminAppManagementTestCase(unittest.TestCase):
    def test_disabling_app_stops_its_live_sidecars(self) -> None:
        binding = self._binding(status="disabled")
        with (
            patch("core.api.admin_app_management.transition_workspace_app_status", return_value=binding),
            patch("core.api.admin_app_management.stop_app_sidecars") as stop_sidecars,
        ):
            status, payload = self._invoke(method="PATCH", body={"status": "disabled"})

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["status"], "disabled")
        stop_sidecars.assert_called_once_with(workspace_id="default", app_id="probe")

    def test_enabling_app_does_not_stop_sidecars(self) -> None:
        binding = self._binding(status="enabled")
        with (
            patch("core.api.admin_app_management.transition_workspace_app_status", return_value=binding),
            patch("core.api.admin_app_management.stop_app_sidecars") as stop_sidecars,
        ):
            status, payload = self._invoke(method="PATCH", body={"status": "enabled"})

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["status"], "enabled")
        stop_sidecars.assert_not_called()

    def test_uninstalling_app_stops_its_live_sidecars(self) -> None:
        with (
            patch("core.api.admin_app_management.uninstall_workspace_app") as uninstall,
            patch("core.api.admin_app_management.stop_app_sidecars") as stop_sidecars,
        ):
            status, payload = self._invoke(method="DELETE", body={})

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["status"], "uninstalled")
        uninstall.assert_called_once()
        stop_sidecars.assert_called_once_with(workspace_id="default", app_id="probe")

    def _invoke(self, *, method: str, body: dict) -> tuple[str, dict]:
        captured: dict[str, str] = {}

        def start_response(status: str, _headers: list[tuple[str, str]]) -> None:
            captured["status"] = status

        response = handle_admin_app_management_api(
            SimpleNamespace(app_store=object(), observability_store=object()),
            SimpleNamespace(),
            {
                "PATH_INFO": "/api/admin/workspace-apps/default/probe",
                "REQUEST_METHOD": method,
            },
            start_response,
            body=body,
            start_path=Path("/unused"),
        )
        assert response is not None
        return captured["status"], json.loads(b"".join(response).decode("utf-8"))

    def _binding(self, *, status: WorkspaceAppStatus) -> WorkspaceAppBindingRecord:
        return WorkspaceAppBindingRecord(
            binding_id="binding-1",
            workspace_id="default",
            app_id="probe",
            source_record_id="source-1",
            source_kind="platform",
            status=status,
            active_version="1.0.0",
            data_root="/data/probe",
            installed_at="2026-08-03T00:00:00+00:00",
            updated_at="2026-08-03T00:00:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
