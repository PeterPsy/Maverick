from __future__ import annotations

import unittest

from core.providers.models import ProviderModelOption, ProviderReasoningOption
from core.providers.provider_codex import build_codex_definition
from core.providers.provider_codex_reasoning import normalize_codex_model_option


def reasoning(effort: str) -> ProviderReasoningOption:
    return ProviderReasoningOption(effort=effort, label=effort.title())


class CodexReasoningDefaultsTest(unittest.TestCase):
    def test_codex_uses_max_and_excludes_multi_agent_ultra(self) -> None:
        option = ProviderModelOption(
            model_id="gpt-5.6-sol",
            label="GPT-5.6-Sol",
            description=None,
            default_reasoning_effort="low",
            supported_reasoning_efforts=[
                reasoning("low"),
                reasoning("medium"),
                reasoning("high"),
                reasoning("xhigh"),
                reasoning("max"),
                reasoning("ultra"),
            ],
        )

        definition = build_codex_definition(model_options=[option])
        normalized = definition.model_options[0]

        self.assertEqual(normalized.default_reasoning_effort, "max")
        self.assertEqual(
            [item.effort for item in normalized.supported_reasoning_efforts],
            ["low", "medium", "high", "xhigh", "max"],
        )

    def test_codex_uses_the_deepest_supported_single_agent_effort(self) -> None:
        option = ProviderModelOption(
            model_id="gpt-5.5",
            label="GPT-5.5",
            description=None,
            default_reasoning_effort="medium",
            supported_reasoning_efforts=[
                reasoning("low"),
                reasoning("medium"),
                reasoning("high"),
                reasoning("xhigh"),
            ],
        )

        normalized = normalize_codex_model_option(option)

        self.assertEqual(normalized.default_reasoning_effort, "xhigh")


if __name__ == "__main__":
    unittest.main()
