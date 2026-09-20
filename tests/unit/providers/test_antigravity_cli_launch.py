"""Antigravity launch modes, workspace boundaries and reasoning selection."""

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.antigravity_cli_sandbox import antigravity_stream_launch_spec
from tests.unit.providers.antigravity_cli_fixture import AntigravityCliFixture


class AntigravityCliLaunchTest(AntigravityCliFixture, unittest.IsolatedAsyncioTestCase):
    async def test_sandbox_launch_is_machine_readable_and_workspace_writable(self):
        command = self.spec.command
        sandboxed = self.sandboxed_spec.command
        workspace = str(Path(self.session.workspace_root))
        self.assertIn(
            ["--bind", workspace, workspace],
            [sandboxed[index : index + 3] for index in range(len(sandboxed) - 2)],
        )
        skills_root = str(
            self.root
            / "runtime/antigravity-home/.gemini/config/skills"
        )
        self.assertIn(
            ["--ro-bind", skills_root, skills_root],
            [sandboxed[index : index + 3] for index in range(len(sandboxed) - 2)],
        )
        self.assertEqual(command.count("stream-json"), 2)
        self.assertEqual(command[command.index("--add-dir") + 1], workspace)
        self.assertIn("--sandbox", command)
        self.assertIn("--disable-slash-commands", command)
        self.assertIn("--model", command)
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertIn("/usr/local/lib", self.spec.readable_roots)
        self.assertEqual(self.spec.env_overrides["HOME"], str(self.root / "runtime/antigravity-home"))
        self.assertNotEqual(self.spec.env_overrides["HOME"], str(Path.home()))
        self.assertNotIn("GEMINI_API_KEY", self.spec.env_overrides)
        self.assertNotIn("MAVERICK_PROVIDER_SECRET", self.spec.env_overrides)
        settings_path = (
            Path(self.spec.env_overrides["HOME"])
            / ".gemini/antigravity-cli/settings.json"
        )
        self.assertEqual(
            json.loads(settings_path.read_text(encoding="utf-8")),
            {
                "artifactReviewPolicy": "asks-for-review",
                "enableTerminalSandbox": True,
                "permissions": {
                    "allow": [
                        "command(maverick)",
                        "unsandboxed(maverick)",
                    ],
                },
                "toolPermission": "proceed-in-sandbox",
            },
        )
        self.assertEqual(settings_path.stat().st_mode & 0o777, 0o600)
        token_path = settings_path.parent / "antigravity-oauth-token"
        self.assertEqual(token_path.read_text(encoding="utf-8"), "fixture-oauth-token")
        self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.spec.resolved_secret_refs, [])
        self.assertIsNone(self.spec.credential_binding_id)
        self.assertEqual(
            self.spec.writable_roots,
            [workspace, str(self.root / "runtime")],
        )
        self.assertTrue(
            (self.root / "runtime/bin/maverick").is_file()
        )
        self.assertIn("MAVERICK_RUNTIME_API_TOKEN", self.spec.env_overrides)
        self.assertTrue(
            self.spec.env_overrides["PATH"].startswith(
                str(self.root / "runtime/bin")
            )
        )

    async def test_launch_maps_the_selected_effort_to_the_catalog_variant(self):
        binding = SimpleNamespace(
            **{
                **vars(self.binding),
                "model_id": "gemini-3.8-flash-high",
                "reasoning_effort": "low",
            }
        )
        with patch(
            "core.providers.antigravity_cli_sandbox.build_bwrap_command",
            side_effect=lambda **kwargs: [
                "fake-bwrap",
                "--bind",
                str(kwargs["workspace_root"]),
                str(kwargs["workspace_root"]),
                "--",
                *kwargs["command"],
            ],
        ):
            spec = antigravity_stream_launch_spec(
                SimpleNamespace(
                    session=self.session,
                    binding=binding,
                    secret_env={},
                ),
                command=self.engine.command,
                dependency_roots=self.engine.dependency_roots,
                auth_home=self.auth_home,
            )

        model_index = spec.command.index("--model")
        effort_index = spec.command.index("--effort")
        self.assertEqual(spec.command[model_index + 1], "gemini-3.8-flash-low")
        self.assertEqual(spec.command[effort_index + 1], "low")

    async def test_full_access_launch_uses_native_cli_permission_bypass(self):
        session = SimpleNamespace(
            **{
                **vars(self.session),
                "effective_mode": "full-access",
            }
        )
        with patch(
            "core.providers.antigravity_cli_sandbox.build_bwrap_command"
        ) as sandbox:
            spec = antigravity_stream_launch_spec(
                SimpleNamespace(
                    session=session,
                    binding=self.binding,
                    secret_env={},
                ),
                command=self.engine.command,
                dependency_roots=self.engine.dependency_roots,
                auth_home=self.auth_home,
            )

        sandbox.assert_not_called()
        self.assertEqual(spec.execution_mode, "full-access")
        self.assertNotIn("--sandbox", spec.command)
        self.assertIn("--dangerously-skip-permissions", spec.command)
        self.assertEqual(spec.working_directory, self.session.workspace_root)
        self.assertEqual(
            spec.command[spec.command.index("--add-dir") + 1],
            self.session.workspace_root,
        )
        self.assertEqual(spec.readable_roots, ["/"])
        self.assertEqual(spec.writable_roots, ["/"])
        self.assertEqual(
            spec.env_overrides["MAVERICK_EFFECTIVE_MODE"],
            "full-access",
        )

    async def test_full_access_turn_accepts_cli_permission_mode_and_effort_variant(self):
        self.session.effective_mode = "full-access"
        self.binding.model_id = "gemini-3.8-flash-high"
        self.binding.reasoning_effort = "low"
        spec = antigravity_stream_launch_spec(
            SimpleNamespace(
                session=self.session,
                binding=self.binding,
                secret_env={},
            ),
            command=self.engine.command,
            dependency_roots=self.engine.dependency_roots,
            auth_home=self.auth_home,
        )
        spec = replace(
            spec,
            env_overrides={
                **spec.env_overrides,
                "ANTIGRAVITY_FIXTURE_PERMISSION": "always-proceed",
                "ANTIGRAVITY_FIXTURE_TRACE": str(self.trace),
            },
        )
        self.spec = spec
        self.context.local_launch_spec = spec
        self.engine.build_launch_spec.return_value = spec

        events = await self.collect("full-access")

        self.assertEqual(self.final_text(events), "answer:full-access")
        startup = next(
            message["startup"]["argv"]
            for message in self.messages()
            if "startup" in message
        )
        model_index = startup.index("--model")
        self.assertEqual(startup[model_index + 1], "gemini-3.8-flash-low")
