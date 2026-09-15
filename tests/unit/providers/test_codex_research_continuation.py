from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from core.providers import codex_app_server_runtime_process as runtime_process
from core.providers import codex_app_server_runtime_thread as runtime_thread
from core.providers.models import RuntimeBackendLaunchSpec


class CodexResearchContinuationTest(unittest.TestCase):
    def test_new_process_resumes_durable_private_research_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime_home = root / "codex-home"
            rollout = runtime_home / "sessions" / "research.jsonl"
            rollout.parent.mkdir(parents=True)
            rollout.write_text("{}\n", encoding="utf-8")
            thread_id = "research-thread"
            with closing(sqlite3.connect(runtime_home / "state_5.sqlite")) as db:
                db.execute(
                    "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT INTO threads VALUES (?, ?)",
                    (thread_id, str(rollout)),
                )
                db.commit()

            runtime = runtime_process._CodexAppServerRuntime(
                session_id="research-session",
                workspace_id="default",
                runtime_root=str(root),
                runtime_home=str(runtime_home),
                process=SimpleNamespace(pid=1, poll=lambda: None),
                research=True,
            )
            session = SimpleNamespace(
                session_id=runtime.session_id,
                workspace_id=runtime.workspace_id,
                runtime_root=runtime.runtime_root,
                runtime_profile="research",
                provider_thread_id=thread_id,
                device_use_binding=None,
            )
            launch_spec = RuntimeBackendLaunchSpec(
                provider_id="codex",
                command=["codex", "app-server"],
                env_overrides={"CODEX_HOME": str(runtime_home)},
                credential_binding_id=None,
                resolved_secret_refs=[],
                working_directory=str(root / "research-workdir"),
                execution_mode="full-access",
                readable_roots=[str(root)],
                writable_roots=[str(root)],
            )

            with patch.object(
                runtime_thread,
                "_send_request",
                return_value={"thread": {"id": thread_id}},
            ) as send_request:
                resumed = runtime_thread._ensure_provider_thread(
                    runtime=runtime,
                    session=session,
                    launch_spec=launch_spec,
                    on_provider_thread_id=None,
                )

        self.assertEqual(resumed, thread_id)
        self.assertEqual(send_request.call_args.args[1], "thread/resume")
        self.assertFalse(send_request.call_args.args[2]["ephemeral"])


if __name__ == "__main__":
    unittest.main()
