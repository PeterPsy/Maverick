from __future__ import annotations

import unittest

from core.api.runtime_api import _validate_research_session_request
from core.providers.errors import ProviderError


class RuntimeApiResearchProfileTest(unittest.TestCase):
    def test_accepts_only_the_fixed_chat_research_contract(self) -> None:
        body = {
            "runtime_profile": "research",
            "runtime_mode": "agentic",
            "agent_id": "research",
            "source_app_id": "chat",
            "requested_mode": "full-access",
            "skill_activation_mode": "explicit",
        }

        _validate_research_session_request(
            body,
            runtime_mode="agentic",
            runtime_profile="research",
        )

        forbidden_values = {
            "system_prompt": "persona",
            "skill_ids": ["research-skill"],
            "attachments": [{"name": "workspace.txt"}],
            "app_references": [{"app_id": "storage"}],
            "project_id": "project-1",
            "device_use_activation_id": "activation-1",
        }
        for field, value in forbidden_values.items():
            with self.subTest(field=field), self.assertRaisesRegex(
                ProviderError,
                "research_runtime_contract_invalid",
            ):
                _validate_research_session_request(
                    {**body, field: value},
                    runtime_mode="agentic",
                    runtime_profile="research",
                )

    def test_workspace_profile_is_not_changed(self) -> None:
        _validate_research_session_request(
            {"system_prompt": "normal agent persona"},
            runtime_mode="agentic",
            runtime_profile="workspace",
        )


if __name__ == "__main__":
    unittest.main()
