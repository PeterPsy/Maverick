"""A connected Mac can continue a chat after its provider process is replaced."""

from contextlib import closing
from datetime import UTC, datetime
import importlib
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

importlib.import_module("core.providers.codex_app_server_runtime")
from core.device_use.models import DeviceUseSessionBinding
from core.providers import codex_app_server_runtime_thread as runtime_thread
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime
from core.providers.models import RuntimeBackendLaunchSpec


class CodexDeviceUseContinuationTests(unittest.TestCase):
    def test_replacement_process_resumes_the_same_private_thread_in_both_modes(self):
        for mode in ("on", "full"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                home = root / "codex-home"
                home.mkdir()
                binding = DeviceUseSessionBinding(
                    activation_id="activation", workspace_id="default", owner_user_id="user",
                    protocol_version="maverick.device-use.v1", executor_contract="macos-v46",
                    tool_contract_digest="a" * 64, mode=mode, initial_app="com.apple.Safari",
                    approved_apps=("com.apple.Safari",), created_at=datetime.now(UTC),
                )
                session = SimpleNamespace(
                    session_id="device-chat", workspace_id="default", runtime_root=str(root),
                    provider_thread_id=None, device_use_binding=binding,
                    execution_binding=SimpleNamespace(model_id="gpt-6.1-sol"),
                )
                launch = RuntimeBackendLaunchSpec(
                    provider_id="codex", command=["codex", "app-server"],
                    env_overrides={"CODEX_HOME": str(home)}, credential_binding_id=None,
                    resolved_secret_refs=[], working_directory=str(root / "workspace"),
                    execution_mode="sandbox", readable_roots=[], writable_roots=[],
                )

                def process():
                    return _CodexAppServerRuntime(
                        session_id=session.session_id, workspace_id=session.workspace_id,
                        runtime_root=str(root), runtime_home=str(home),
                        process=SimpleNamespace(pid=1, poll=lambda: None), device_use_binding=binding,
                    )

                def start(_runtime, method, params, **_kwargs):
                    self.assertEqual(method, "thread/start")
                    # Model the provider's archive contract: ephemeral threads
                    # have no rollout for a later process to resume.
                    if not params["ephemeral"]:
                        rollout = home / "sessions" / "device.jsonl"
                        rollout.parent.mkdir()
                        rollout.write_text("{}\n", encoding="utf-8")
                        with closing(sqlite3.connect(home / "state_5.sqlite")) as db:
                            db.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL)")
                            db.execute("INSERT INTO threads VALUES (?, ?)", ("device-provider-thread", str(rollout)))
                            db.commit()
                    return {"thread": {"id": "device-provider-thread"}}

                with patch.object(runtime_thread, "_send_request", side_effect=start):
                    thread_id = runtime_thread._ensure_provider_thread(
                        runtime=process(), session=session, launch_spec=launch,
                    )
                session.provider_thread_id = thread_id
                replacement = process()
                with patch.object(runtime_thread, "_send_request", return_value={"thread": {"id": thread_id}}) as send:
                    resumed = runtime_thread._ensure_provider_thread(
                        runtime=replacement, session=session, launch_spec=launch,
                    )
                    # A third turn in the same process reuses its loaded thread.
                    again = runtime_thread._ensure_provider_thread(
                        runtime=replacement, session=session, launch_spec=launch,
                    )
                self.assertEqual((resumed, again), (thread_id, thread_id))
                send.assert_called_once()
                self.assertEqual(send.call_args.args[1], "thread/resume")
                params = send.call_args.args[2]
                self.assertFalse(params["ephemeral"])
                self.assertEqual(params["model"], "gpt-6.1-sol")
                self.assertEqual(params["sandbox"], "read-only")
                self.assertEqual(replacement.device_use_binding, binding)


if __name__ == "__main__":
    unittest.main()
