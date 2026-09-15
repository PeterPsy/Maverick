from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tomllib
import unittest
from unittest.mock import patch

importlib.import_module("core.providers.codex_app_server_runtime")
from core.providers import codex_app_server_runtime_protocol as runtime_protocol
from core.providers.codex_app_server_device_use_turn import (
    codex_turn_input,
    codex_turn_start_params,
)
from core.providers.codex_app_server_runtime_thread_params import (
    CODEX_RESEARCH_DISABLED_FEATURES,
    CODEX_RESEARCH_ENABLED_FEATURES,
    codex_thread_params,
)
from core.providers.provider_codex import CodexProviderAdapter
from core.providers.provider_codex_research import (
    codex_research_runtime_version,
    validate_codex_research_initialize,
)
from core.providers.errors import ProviderLaunchError
from core.runtime.turn_submission_service_output import (
    _build_launch_spec_for_execution,
)


class CodexResearchRuntimeTest(unittest.TestCase):
    def test_runtime_version_and_private_home_are_positively_attested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            command = root / "codex"
            command.write_text(
                "#!/bin/sh\nprintf 'codex-cli 0.153.4\\n'\n",
                encoding="utf-8",
            )
            command.chmod(0o755)
            codex_research_runtime_version.cache_clear()

            self.assertEqual(
                codex_research_runtime_version(str(command)),
                "0.153.4",
            )
            validate_codex_research_initialize(
                {"codexHome": str(root / "home")},
                expected_home=str(root / "home"),
            )
            with self.assertRaises(ProviderLaunchError):
                validate_codex_research_initialize(
                    {"codexHome": str(root / "other")},
                    expected_home=str(root / "home"),
                )

    def test_non_web_native_tool_event_fails_closed(self) -> None:
        process = SimpleNamespace(terminate=unittest.mock.Mock())
        runtime = SimpleNamespace(
            research=True,
            process=process,
            event_lock=unittest.mock.MagicMock(),
            current_error_text=None,
            current_failure_reason_code=None,
            current_terminal_error_at=None,
        )
        with patch.object(runtime_protocol, "_put_completion") as complete, patch.object(
            runtime_protocol,
            "_emit",
        ) as emit:
            runtime_protocol._handle_item_event(
                runtime,
                provider_type="item.started",
                item={"type": "commandExecution", "command": "pwd"},
            )

        self.assertEqual(
            runtime.current_failure_reason_code,
            "research_runtime_unavailable",
        )
        complete.assert_called_once_with(runtime, {"status": "failed"})
        process.terminate.assert_called_once()
        emit.assert_not_called()

    def test_thread_is_durable_and_turn_is_web_only_without_instructions(self) -> None:
        session = SimpleNamespace(
            runtime_profile="research",
            device_use_binding=None,
        )
        launch_spec = SimpleNamespace(
            working_directory="/private/research",
            execution_mode="full-access",
        )

        params = codex_thread_params(session=session, launch_spec=launch_spec)
        device_use, research, turn_input = codex_turn_input(
            session,
            SimpleNamespace(runtime_root="/unused", runtime_home="/unused"),
            "Find current primary sources.",
            invoked_skills=(),
        )
        turn = codex_turn_start_params(
            device_use=device_use,
            research=research,
            provider_thread_id="thread-research",
            turn_input=turn_input,
            reasoning_effort=None,
            launch_spec=launch_spec,
            sandbox_policy=lambda _spec: {"type": "dangerFullAccess"},
        )

        self.assertFalse(params["ephemeral"])
        self.assertEqual(params["sandbox"], "read-only")
        self.assertEqual(params["environments"], [])
        self.assertEqual(params["baseInstructions"], "")
        self.assertEqual(params["developerInstructions"], "")
        self.assertEqual(params["personality"], "none")
        self.assertEqual(params["config"]["web_search"], "live")
        self.assertEqual(params["config"]["mcp_servers"], {})
        self.assertTrue(
            all(
                params["config"]["features"][feature] is False
                for feature in CODEX_RESEARCH_DISABLED_FEATURES
            )
        )
        self.assertTrue(
            all(
                params["config"]["features"][feature] is True
                for feature in CODEX_RESEARCH_ENABLED_FEATURES
            )
        )
        self.assertEqual(
            params["config"]["skills"],
            {"bundled": {"enabled": False}, "include_instructions": False},
        )
        self.assertEqual(turn_input, [{"type": "text", "text": "Find current primary sources."}])
        self.assertEqual(turn["sandboxPolicy"], {"type": "readOnly"})
        self.assertEqual(turn["environments"], [])
        self.assertNotIn("cwd", turn)

    def test_launch_uses_only_auth_and_an_empty_sandboxed_workdir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_home = root / "operator-codex"
            source_home.mkdir()
            (source_home / "auth.json").write_text(
                '{"auth_mode":"chatgpt"}\n',
                encoding="utf-8",
            )
            (source_home / "config.toml").write_text(
                'developer_instructions = "operator bias"\n',
                encoding="utf-8",
            )
            (source_home / "rules").mkdir()
            (source_home / "rules" / "default.rules").write_text(
                "operator rule\n",
                encoding="utf-8",
            )
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "AGENTS.md").write_text(
                "workspace bias\n",
                encoding="utf-8",
            )
            runtime_root = root / "runtime"
            vendor_bin = root / "vendor"
            vendor_bin.mkdir()
            codex = vendor_bin / "codex"
            codex.write_text("not executed\n", encoding="utf-8")
            codex.chmod(0o755)
            (vendor_bin / "codex-code-mode-host").touch()
            session = SimpleNamespace(
                session_id="research-session",
                workspace_id="default",
                runtime_profile="research",
                runtime_root=str(runtime_root),
                workspace_root=str(workspace),
                workdir=str(workspace),
                effective_mode="full-access",
                skill_activation_mode="implicit",
                device_use_binding=None,
            )

            with patch.dict(
                "os.environ",
                {"MAVERICK_CODEX_HOME": str(source_home)},
                clear=False,
            ):
                spec = CodexProviderAdapter(codex_command=str(codex)).build_launch_spec(
                    session,
                    model_id="gpt-5.6-sol",
                    model_reasoning_effort="high",
                )

            runtime_home = runtime_root / "codex-home"
            config_text = (runtime_home / "config.toml").read_text(encoding="utf-8")
            config = tomllib.loads(config_text)
            research_workdir = runtime_root / "research-workdir"

            self.assertEqual(spec.working_directory, str(research_workdir))
            self.assertEqual(tuple(research_workdir.iterdir()), ())
            self.assertIn("workspace_sandbox.py", " ".join(spec.command))
            self.assertIn(str(research_workdir), spec.command)
            self.assertNotIn(str(workspace), spec.command)
            self.assertEqual(spec.writable_roots, [str(runtime_root)])
            self.assertTrue((runtime_home / "auth.json").is_file())
            self.assertFalse((runtime_home / "rules").exists())
            self.assertFalse((runtime_home / "skills").exists())
            self.assertNotIn("operator bias", config_text)
            self.assertNotIn("workspace bias", config_text)
            self.assertEqual(config["web_search"], "live")
            self.assertEqual(config["project_doc_max_bytes"], 0)
            self.assertFalse(config["include_environment_context"])
            self.assertTrue(
                all(
                    config["features"][feature] is False
                    for feature in CODEX_RESEARCH_DISABLED_FEATURES
                )
            )
            self.assertTrue(
                all(
                    config["features"][feature] is True
                    for feature in CODEX_RESEARCH_ENABLED_FEATURES
                )
            )
            self.assertEqual(
                config["skills"]["bundled"],
                {"enabled": False},
            )
            self.assertFalse(
                any(key.startswith("MAVERICK_") for key in spec.env_overrides)
            )
            self.assertNotIn("PYTHONPATH", spec.env_overrides)

            with self.assertRaises(ProviderLaunchError):
                CodexProviderAdapter(codex_command=str(codex))._build_subprocess_env(
                    workdir=research_workdir,
                    workspace_root=research_workdir,
                    runtime_root=runtime_root,
                    runtime_home=runtime_home,
                    runtime_bin=runtime_root / "bin",
                    session=session,
                    execution_mode="sandbox",
                    secret_env={"API_KEY": "forbidden"},
                    base_env={"PATH": "/usr/bin"},
                )

            state = SimpleNamespace(
                provider_store=SimpleNamespace(),
                runtime_store=SimpleNamespace(),
                secret_store=None,
                observability_store=None,
                repository_root=root,
            )
            with patch(
                "core.runtime.turn_submission_service_output."
                "build_runtime_backend_launch_spec",
                return_value=spec,
            ), patch(
                "core.runtime.turn_submission_skills."
                "list_available_workspace_skills"
            ) as list_skills, patch(
                "core.runtime.turn_submission_skills."
                "prepare_runtime_skills"
            ) as prepare_skills:
                _resolved, metadata = _build_launch_spec_for_execution(
                    state,
                    session=session,
                    provider_id="codex",
                    runtime_adapter=CodexProviderAdapter(
                        codex_command=str(codex)
                    ),
                )

            self.assertEqual(metadata["skill_count"], 0)
            list_skills.assert_not_called()
            prepare_skills.assert_not_called()
            self.assertFalse((runtime_home / "skills").exists())


if __name__ == "__main__":
    unittest.main()
