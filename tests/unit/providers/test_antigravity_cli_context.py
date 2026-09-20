"""Native context parity through Antigravity's actual structured transport."""

from pathlib import Path
import unittest
from unittest.mock import patch

from core.skills.models import SkillDefinition
from core.providers.antigravity_cli_runtime_home import antigravity_runtime_skill_root
from tests.unit.providers.antigravity_cli_fixture import AntigravityCliFixture


class AntigravityCliContextTest(AntigravityCliFixture, unittest.IsolatedAsyncioTestCase):
    async def test_context_preserves_workspace_agent_skills_and_user_input_on_resume(self):
        workspace = Path(self.session.workspace_root)
        instructions = workspace / "AGENTS.md"
        instructions.write_text("Use the main repository for built-in apps.\n")
        self.session.system_prompt = "You are the workspace's engineering assistant."
        skill_root = workspace / "skills" / "engineering"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text("# Engineering\nRead the code first.\n")
        self.context.invoked_skills = (SkillDefinition(
            skill_id="engineering", local_skill_id="engineering",
            name="Engineering", description="Repository workflow.",
            source_root=str(skill_root), owner_kind="workspace",
            owner_id="default", workspace_id="default", status="available",
        ),)
        prompt = "Inspect the repo.\n\nReferenced app: chat\nAttachment: storage/sample.txt"
        for index in range(2):
            await self.controller.prepare(self.context)
            self.assertEqual(self.final_text(await self.collect(prompt)), "answer:" + prompt)
            wire = [message for message in self.messages() if message.get("event") == "user"][-1]
            text = wire["message"]["content"]
            self.assertIn(str(workspace), text)
            self.assertIn('"execution_mode": "sandbox"', text)
            self.assertIn(instructions.read_text(), text)
            self.assertIn(self.session.system_prompt, text)
            self.assertIn("Engineering", text)
            self.assertIn("SKILL.md", text)
            copied_skill = antigravity_runtime_skill_root(
                Path(self.session.runtime_root), "engineering",
            ) / "SKILL.md"
            self.assertIn(str(copied_skill), text)
            self.assertEqual(copied_skill.read_text(), (skill_root / "SKILL.md").read_text())
            self.assertTrue(text.endswith("[Maverick user input]\n" + prompt))
            self.assertNotIn("fixture-oauth-token", text)
            if index == 0:
                instructions.write_text("Updated workspace instructions.\n")
                await self.controller.close(self.context)

    async def test_implicit_sessions_receive_available_catalog_without_invocations(self):
        self.session.skill_activation_mode = "implicit"
        skill_root = Path(self.session.workspace_root) / "engineering"
        skill_root.mkdir()
        (skill_root / "SKILL.md").write_text("# Engineering\n")
        skill = SkillDefinition(
            skill_id="engineering", local_skill_id="engineering", name="Engineering",
            description="Repository workflow.", source_root=str(skill_root),
            owner_kind="workspace", owner_id="default", workspace_id="default",
            status="available",
        )
        with patch(
            "core.providers.antigravity_cli_native.resolve_available_runtime_skills",
            return_value=[skill],
        ) as resolve:
            await self.controller.prepare(self.context)
        resolve.assert_called_once_with(self.session)
        await self.collect("Inspect the repository")
        wire = [message for message in self.messages() if message.get("event") == "user"][-1]
        self.assertIn("Engineering", wire["message"]["content"])
        self.assertEqual(len(list((self.root / "runtime/antigravity-home").rglob("SKILL.md"))), 1)

        with patch(
            "core.providers.antigravity_cli_native.resolve_available_runtime_skills",
            return_value=[],
        ):
            await self.controller.prepare(self.context)
        await self.collect("Inspect again")
        wire = [message for message in self.messages() if message.get("event") == "user"][-1]
        self.assertNotIn("Engineering", wire["message"]["content"])
        self.assertEqual(list((self.root / "runtime/antigravity-home").rglob("SKILL.md")), [])
