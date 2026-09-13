from __future__ import annotations

from datetime import UTC, datetime
import tempfile

from core.api.platform_host import PlatformHost
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.unit.api.test_inter_agent_api import (
    InterAgentApiSupport,
    _run_payload_without_snapshot,
)


class DeviceUseInterAgentApiTestCase(InterAgentApiSupport):
    def test_device_use_root_rejects_every_multi_agent_entrypoint(self) -> None:
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

        self.assertEqual(run_status, 409)
        self.assertEqual(run_payload["error"], "device_use_requires_codex_mono_agent_chat")
        self.assertEqual(orchestration_status, 409)
        self.assertEqual(
            orchestration_payload["error"],
            "device_use_requires_codex_mono_agent_chat",
        )
