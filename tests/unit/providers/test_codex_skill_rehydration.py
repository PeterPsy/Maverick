from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

importlib.import_module("core.providers.codex_app_server_runtime")
from core.providers import codex_app_server_skill_rehydration as skill_rehydration
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime
from core.skills.models import SkillDefinition


class CodexSkillRehydrationTestCase(unittest.TestCase):
    def test_completed_context_compaction_resteers_structured_skills_into_same_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir) / "runtime"
            skill_file = runtime_root / "codex-home" / "skills" / "storage-ops" / "SKILL.md"
            skill_file.parent.mkdir(parents=True)
            skill_file.write_text("# Storage Ops\n", encoding="utf-8")
            runtime = _CodexAppServerRuntime(
                session_id="session-compaction",
                workspace_id="default",
                runtime_root=str(runtime_root),
                process=SimpleNamespace(pid=123, poll=lambda: None),
                provider_thread_id="provider-thread-1",
                current_provider_turn_id="provider-turn-1",
            )
            invoked_skill = SkillDefinition(
                skill_id="storage-ops",
                local_skill_id="storage-ops",
                name="Storage Ops",
                description="Operate Storage.",
                source_root="/catalog/storage-ops",
                owner_kind="workspace",
                owner_id="default",
                workspace_id="default",
                status="available",
            )
            runtime.current_invoked_skills = (invoked_skill,)

            with patch.object(
                skill_rehydration,
                "_send_request",
                return_value={"turnId": "provider-turn-1"},
            ) as send_request:
                result = skill_rehydration._rehydrate_codex_skills_after_compaction(
                    runtime,
                    expected_provider_thread_id="provider-thread-1",
                    expected_provider_turn_id="provider-turn-1",
                    invoked_skills=(invoked_skill,),
                )

        self.assertTrue(result)
        self.assertEqual(
            send_request.call_args.args[2],
            {
                "threadId": "provider-thread-1",
                "expectedTurnId": "provider-turn-1",
                "input": [
                    {
                        "type": "text",
                        "text": "Restore the explicitly invoked skill instructions after context compaction, then continue the current task without changing its objective.",
                    },
                    {"type": "skill", "name": "storage-ops", "path": str(skill_file.resolve())},
                ],
            },
        )

    def test_completed_context_compaction_schedules_rehydration_once(self) -> None:
        runtime = _CodexAppServerRuntime(
            session_id="session-compaction-schedule",
            workspace_id="default",
            runtime_root="/tmp/session-compaction-schedule",
            process=SimpleNamespace(pid=123, poll=lambda: None),
            provider_thread_id="provider-thread-1",
            current_provider_turn_id="provider-turn-1",
        )
        runtime.current_invoked_skills = (
            SkillDefinition(
                skill_id="storage-ops",
                local_skill_id="storage-ops",
                name="Storage Ops",
                description="Operate Storage.",
                source_root="/catalog/storage-ops",
                owner_kind="workspace",
                owner_id="default",
                workspace_id="default",
                status="available",
            ),
        )
        started_threads = []

        class DeferredThread:
            def __init__(self, **kwargs):
                started_threads.append(kwargs)

            def start(self):
                return None

        with patch.object(skill_rehydration.threading, "Thread", DeferredThread):
            first = skill_rehydration.schedule_codex_skill_rehydration(
                runtime,
                compaction_item_id="compact-1",
            )
            duplicate = skill_rehydration.schedule_codex_skill_rehydration(
                runtime,
                compaction_item_id="compact-1",
            )

        self.assertTrue(first)
        self.assertFalse(duplicate)
        self.assertEqual(len(started_threads), 1)


if __name__ == "__main__":
    unittest.main()
