from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers import codex_app_server_runtime_thread as runtime_thread


class CodexAppServerRuntimeInitializeTestCase(unittest.TestCase):
    def test_standard_runtime_keeps_stable_initialize_handshake(self) -> None:
        params = self._initialize_params(device_use_binding=None)

        self.assertEqual(
            params,
            {"clientInfo": {"name": "maverick", "version": "3.0.0"}},
        )

    def test_device_use_runtime_negotiates_experimental_api(self) -> None:
        params = self._initialize_params(
            device_use_binding=SimpleNamespace(activation_id="activation"),
        )

        self.assertEqual(
            params,
            {
                "clientInfo": {"name": "maverick", "version": "3.0.0"},
                "capabilities": {"experimentalApi": True},
            },
        )

    def test_research_runtime_negotiates_environment_isolation(self) -> None:
        params = self._initialize_params(
            device_use_binding=None,
            runtime_profile="research",
        )

        self.assertEqual(
            params,
            {
                "clientInfo": {
                    "name": "research-client",
                    "version": "1.0.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )

    def _initialize_params(
        self,
        *,
        device_use_binding,
        runtime_profile="workspace",
    ):
        session = SimpleNamespace(
            session_id=f"session-initialize-{device_use_binding is not None}",
            workspace_id="default",
            runtime_root="/tmp/runtime-initialize",
            device_use_binding=device_use_binding,
            runtime_profile=runtime_profile,
        )
        launch_spec = SimpleNamespace(
            command=["codex", "app-server"],
            working_directory="/tmp",
            env_overrides={"CODEX_HOME": "/tmp/runtime-initialize/codex-home"},
        )

        class FakeProcess:
            pid = 4321
            stdout: list[str] = []

            @staticmethod
            def poll():
                return None

        process = FakeProcess()
        thread = SimpleNamespace(start=lambda: None)
        runtime_thread._RUNTIMES.pop(session.session_id, None)
        try:
            with patch.object(runtime_thread, "configure_runtime_process_oom_score"), patch.object(
                runtime_thread,
                "register_runtime_process",
            ), patch.object(
                runtime_thread.threading,
                "Thread",
                return_value=thread,
            ), patch.object(
                runtime_thread,
                "start_device_use_request_worker",
            ), patch.object(
                runtime_thread,
                "_send_request",
                return_value=(
                    {"codexHome": "/tmp/runtime-initialize/codex-home"}
                    if runtime_profile == "research"
                    else {}
                ),
            ) as send_request:
                runtime_thread._ensure_runtime(
                    session=session,
                    launch_spec=launch_spec,
                    command_runner=lambda *_args, **_kwargs: process,
                )
        finally:
            runtime_thread._RUNTIMES.pop(session.session_id, None)

        self.assertEqual(send_request.call_args.args[1], "initialize")
        return send_request.call_args.args[2]


if __name__ == "__main__":
    unittest.main()
