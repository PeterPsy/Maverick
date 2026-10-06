"""Research uses the selected Antigravity model without workspace authority."""

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.antigravity_cli_research import (
    ANTIGRAVITY_RESEARCH_AGENT,
    antigravity_research_launch_spec,
    validate_antigravity_research_step,
)
from core.providers.native_structured_cli_transport import NativeStructuredCliError
from core.runtime.research_runtime import RESEARCH_BOUNDARY_INSTRUCTION, research_runtime_kind
from tests.unit.providers.antigravity_cli_fixture import AntigravityCliFixture


class AntigravityResearchTest(AntigravityCliFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await self.setup_fixture()
        self.session.runtime_profile = "research"
        self.session.effective_mode = "full-access"
        self.session.workspace_root = str(self.root / "inaccessible-workspace")
        self.session.workdir = self.session.workspace_root
        with patch(
            "core.providers.antigravity_cli_research.build_bwrap_command",
            side_effect=lambda **kwargs: ["fake-bwrap", "--", *kwargs["command"]],
        ) as sandbox:
            spec = antigravity_research_launch_spec(
                self.context, command=self.engine.command,
                dependency_roots=self.engine.dependency_roots, auth_home=self.auth_home,
            )
        self.sandbox = sandbox.call_args.kwargs
        self.sandboxed_spec = spec
        self.spec = replace(
            spec, command=spec.command[spec.command.index("--") + 1:],
            env_overrides={**spec.env_overrides, "ANTIGRAVITY_FIXTURE_TRACE": str(self.trace)},
        )
        self.context.local_launch_spec = self.spec
        self.engine.build_launch_spec.return_value = self.spec

    async def test_launch_is_private_web_only_and_preserves_the_selected_model(self):
        self.assertTrue(self.controller.research_runtime_available(self.binding))
        identity = SimpleNamespace(
            runtime_engine_id="antigravity-cli", adapter_id=self.engine.adapter_id,
            model_provider_id="google", provider_protocol="antigravity-cli-stream-json",
        )
        self.assertEqual(research_runtime_kind(identity, self.controller), "native-web-only-v1")
        self.assertEqual(self.sandbox["workspace_root"], self.root / "runtime/research-workdir")
        self.assertNotIn(self.session.workspace_root, self.spec.readable_roots)
        self.assertEqual(self.spec.writable_roots, [str(self.root / "runtime")])
        self.assertNotIn("--dangerously-skip-permissions", self.spec.command)
        self.assertNotIn("--add-dir", self.spec.command)
        self.assertFalse(any(key.startswith("MAVERICK_") for key in self.spec.env_overrides))
        self.assertFalse((self.root / "runtime/bin/maverick").exists() and
                         str(self.root / "runtime/bin") in self.spec.env_overrides["PATH"])
        home = Path(self.spec.env_overrides["HOME"])
        agent = (home / ".gemini/config/agents" / ANTIGRAVITY_RESEARCH_AGENT / "agent.md").read_text()
        self.assertIn("tools: [search_web, read_url_content]", agent)
        self.assertIn("inheritCustomizations: false", agent)
        self.assertIn(RESEARCH_BOUNDARY_INSTRUCTION, agent)
        settings = json.loads((home / ".gemini/antigravity-cli/settings.json").read_text())
        self.assertEqual(settings["permissions"], {"allow": []})

    async def test_prepare_skips_skills_and_sends_only_the_conversation(self):
        with patch("core.providers.antigravity_cli_native.resolve_available_runtime_skills") as skills:
            prepared = await self.controller.prepare(self.context)
        self.assertTrue(prepared.ready)
        skills.assert_not_called()
        self.assertEqual(self.final_text(await self.collect("first")), "answer:first")
        self.assertEqual(self.final_text(await self.collect("second")), "answer:second")
        inputs = [item["message"]["content"] for item in self.messages() if item.get("event") == "user"]
        self.assertEqual(inputs, ["first", "second"])

    async def test_wrong_primary_agent_fails_before_a_turn(self):
        self.context.local_launch_spec = replace(self.spec, env_overrides={
            **self.spec.env_overrides, "ANTIGRAVITY_FIXTURE_AGENT": "default",
        })
        with self.assertRaisesRegex(NativeStructuredCliError, "research_runtime_unavailable"):
            await self.controller.prepare(self.context)

    async def test_replaced_unreviewed_runtime_fails_before_launch(self):
        Path(self.engine.command).write_text("#!/bin/sh\nprintf '9.9.9\\n'\n")
        self.assertFalse(self.controller.research_runtime_available(self.binding))
        with self.assertRaisesRegex(NativeStructuredCliError, "research_runtime_unavailable"):
            antigravity_research_launch_spec(
                self.context, command=self.engine.command,
                dependency_roots=self.engine.dependency_roots, auth_home=self.auth_home,
            )

    async def test_forbidden_operational_event_terminates_the_session(self):
        await self.controller.prepare(self.context)
        with self.assertRaisesRegex(NativeStructuredCliError, "research_runtime_unavailable"):
            await self.collect("tool")
        self.assertNotIn(self.session.session_id, self.engine._owners)

    def test_only_web_tools_and_passive_steps_are_accepted(self):
        for name in ("search_web", "read_url_content"):
            validate_antigravity_research_step({"step_type": "tool", "tool_info": {"name": name}})
        for name in ("run_command", "write_to_file", "view_file", "invoke_subagent", "call_mcp_tool"):
            with self.subTest(name=name), self.assertRaises(NativeStructuredCliError):
                validate_antigravity_research_step({"step_type": "tool", "tool_info": {"name": name}})
        with self.assertRaises(NativeStructuredCliError):
            validate_antigravity_research_step({"step_type": "subagent"})


if __name__ == "__main__":
    unittest.main()
