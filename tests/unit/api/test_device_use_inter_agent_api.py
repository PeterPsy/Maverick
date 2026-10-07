from __future__ import annotations

from datetime import UTC, datetime
import tempfile
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.unit.api.test_inter_agent_api import (
    InterAgentApiSupport,
    _run_payload_without_snapshot,
)


class DeviceUseInterAgentApiTestCase(InterAgentApiSupport):
    def test_mac_capability_allows_normal_multi_agent_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root, device_use=True)
            now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
            state.runtime_store.save_turn(RuntimeTurnRecord(
                turn_id="device-turn",
                session_id="root-session",
                workspace_id="default",
                status="completed",
                input_text="Use the Mac",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=now,
                failure_reason=None,
            ))
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            run_status, run_payload, _ = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(run_id="device-run"),
                cookie=cookie,
            )
            spawn_status, spawn_payload, _ = self._invoke(
                app,
                path="/api/inter-agent/runs/device-run/participants",
                method="POST",
                body={"participant_id": "researcher", "child_session_id": "mac-child"},
                cookie=cookie,
            )
            self.assertEqual(spawn_status, 201, spawn_payload)
            self.assertIsNone(state.runtime_store.get_session("mac-child").device_use_binding)
            with patch("core.api.inter_agent_api._start_orchestrated_execution_worker"):
                orchestration_status, orchestration_payload, _ = self._invoke(
                    app,
                    path="/api/inter-agent/orchestrations",
                    method="POST",
                    body={
                        "root_runtime_session_id": "root-session",
                        "source_runtime_turn_id": "device-turn",
                        "policy": "multi",
                    },
                    cookie=cookie,
                )
            self.assertIsNotNone(state.runtime_store.get_session("root-session").device_use_binding)
            for session in state.runtime_store.list_all_sessions():
                if session.session_id != "root-session":
                    self.assertIsNone(session.device_use_binding)

        self.assertEqual(run_status, 201, run_payload)
        self.assertEqual(orchestration_status, 202, orchestration_payload)
