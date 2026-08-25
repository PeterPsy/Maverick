from __future__ import annotations

import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

importlib.import_module("core.providers.codex_app_server_runtime")
from core.providers import codex_app_server_runtime_protocol as runtime_protocol
from core.providers import codex_app_server_runtime_thread as runtime_thread
from core.providers.codex_app_server_runtime_protocol import _handle_notification
from core.providers.codex_prompt_budget import (
    CODEX_EXPLICIT_BASE_INSTRUCTIONS,
    final_prompt_budget_payload,
)
from core.providers.models import RuntimeBackendLaunchSpec


class CodexPromptBudgetTestCase(unittest.TestCase):
    def test_explicit_thread_uses_lean_budgeted_base_instructions(self) -> None:
        launch_spec = RuntimeBackendLaunchSpec(
            provider_id="codex",
            command=["codex", "app-server"],
            env_overrides={},
            credential_binding_id=None,
            resolved_secret_refs=[],
            working_directory="/tmp",
            execution_mode="sandbox",
            readable_roots=[],
            writable_roots=[],
        )
        explicit = runtime_thread._thread_params(
            session=SimpleNamespace(skill_activation_mode="explicit", system_prompt=""),
            launch_spec=launch_spec,
        )
        implicit = runtime_thread._thread_params(
            session=SimpleNamespace(skill_activation_mode="implicit", system_prompt=""),
            launch_spec=launch_spec,
        )

        self.assertEqual(explicit["baseInstructions"], CODEX_EXPLICIT_BASE_INSTRUCTIONS)
        self.assertLess(len(explicit["baseInstructions"]), 1_000)
        self.assertNotIn("Available skills", explicit["baseInstructions"])
        self.assertEqual(explicit["config"]["project_doc_max_bytes"], 2_048)
        self.assertNotIn("baseInstructions", implicit)
        self.assertNotIn("project_doc_max_bytes", implicit["config"])

    def test_real_provider_usage_shape_evaluates_explicit_first_turn_budget(self) -> None:
        runtime = SimpleNamespace(
            provider_thread_id="thread-provider-lean",
            current_provider_turn_id="turn-provider-first",
            prompt_budget_pending=True,
            prompt_budget_turn_id=None,
            prompt_profile="maverick-explicit-lean-v1",
            first_turn_input_token_budget=8_000,
        )

        event = runtime_protocol._codex_usage_event(
            runtime,
            {
                "threadId": "thread-provider-lean",
                "turnId": "turn-provider-first",
                "tokenUsage": {
                    "total": {
                        "inputTokens": 7_450,
                        "cachedInputTokens": 250,
                        "outputTokens": 8,
                        "reasoningOutputTokens": 14,
                        "totalTokens": 7_472,
                    },
                    "last": {
                        "inputTokens": 7_450,
                        "cachedInputTokens": 250,
                        "outputTokens": 8,
                        "reasoningOutputTokens": 14,
                        "totalTokens": 7_472,
                    },
                    "modelContextWindow": 258_400,
                },
            },
            final_snapshot=True,
        )

        self.assertEqual(event.payload["latest_non_cached_input_tokens"], 7_200)
        self.assertEqual(event.payload["first_turn_input_token_budget"], 8_000)
        self.assertTrue(event.payload["first_turn_within_input_budget"])
        self.assertTrue(event.payload["prompt_budget_final"])
        final = final_prompt_budget_payload(runtime)
        self.assertEqual(final["non_cached_input_tokens"], 7_200)
        self.assertTrue(final["within_budget"])

    def test_turn_completion_emits_final_budget_from_separate_usage_notification(self) -> None:
        runtime = SimpleNamespace(
            provider_thread_id="thread-provider-lean",
            current_provider_turn_id="turn-provider-first",
            prompt_budget_pending=True,
            prompt_budget_turn_id="turn-provider-first",
            prompt_profile="maverick-explicit-lean-v1",
            first_turn_input_token_budget=8_000,
            prompt_budget_latest_input_tokens=7_691,
            prompt_budget_latest_cached_input_tokens=0,
            process=SimpleNamespace(pid=123, poll=lambda: None),
        )

        with (
            patch.object(runtime_protocol, "_flush_pending_agent_json_chunks"),
            patch.object(runtime_protocol, "_debug_log"),
            patch.object(runtime_protocol, "_put_completion"),
            patch.object(runtime_protocol, "_emit") as emit,
        ):
            _handle_notification(
                runtime,
                {
                    "method": "turn/completed",
                    "params": {"turn": {"id": "turn-provider-first", "status": "completed"}},
                },
            )

        budget_event = emit.call_args.args[1]
        self.assertEqual(budget_event.event_type, "runtime.prompt_budget.evaluated")
        self.assertEqual(budget_event.payload["non_cached_input_tokens"], 7_691)
        self.assertTrue(budget_event.payload["within_budget"])
        self.assertFalse(runtime.prompt_budget_pending)


if __name__ == "__main__":
    unittest.main()
