from __future__ import annotations

import unittest

from core.runtime.app_references import input_text_with_app_references


class RuntimeAppReferencesTestCase(unittest.TestCase):
    def test_entity_reference_rewrites_stable_token_and_adds_provider_context(self) -> None:
        text = input_text_with_app_references(
            input_text="Review @Agency launch [ref:checklist/checklist/check_123]",
            app_references=[
                {
                    "type": "entity",
                    "app_id": "checklist",
                    "entity_type": "checklist",
                    "entity_id": "check_123",
                    "label": "Agency launch",
                    "summary": "1/3 checked",
                    "deep_link": "/app/checklist/checklists/check_123",
                }
            ],
        )

        self.assertIn("Review app_ref:checklist/checklist/check_123", text)
        self.assertIn("Referenced apps:\n- app_id: checklist", text)
        self.assertIn("Referenced app-owned records:", text)
        self.assertIn("  entity_type: checklist", text)
        self.assertIn("  entity_id: check_123", text)
        self.assertIn("  summary: 1/3 checked", text)
        self.assertNotIn("[ref:checklist/checklist/check_123]", text)

    def test_entity_reference_rewrites_by_marker_after_rename_or_delete(self) -> None:
        text = input_text_with_app_references(
            input_text="Review @Old launch [ref:checklist/checklist/check_123]",
            app_references=[
                {
                    "type": "entity",
                    "app_id": "checklist",
                    "entity_type": "checklist",
                    "entity_id": "check_123",
                    "label": "Renamed launch",
                    "summary": "server summary",
                }
            ],
        )

        self.assertIn("Review app_ref:checklist/checklist/check_123", text)
        self.assertNotIn("@Old launch", text)
        self.assertNotIn("[ref:checklist/checklist/check_123]", text)
        self.assertIn("  label: Renamed launch", text)

    def test_entity_reference_rewrites_only_marker_without_direct_mention_prefix(self) -> None:
        text = input_text_with_app_references(
            input_text="Compare @Chat\nthen [ref:checklist/checklist/check_123]",
            app_references=[
                {
                    "type": "entity",
                    "app_id": "checklist",
                    "entity_type": "checklist",
                    "entity_id": "check_123",
                    "label": "Renamed launch",
                    "summary": "server summary",
                }
            ],
        )

        self.assertIn("Compare @Chat\nthen app_ref:checklist/checklist/check_123", text)
        self.assertNotIn("[ref:checklist/checklist/check_123]", text)

    def test_entity_reference_rewrites_only_marker_after_plain_app_id_text(self) -> None:
        text = input_text_with_app_references(
            input_text="Compare app_id:chat then [ref:checklist/checklist/check_123]",
            app_references=[
                {
                    "type": "entity",
                    "app_id": "checklist",
                    "entity_type": "checklist",
                    "entity_id": "check_123",
                    "label": "Renamed launch",
                }
            ],
        )

        self.assertIn("Compare app_id:chat then app_ref:checklist/checklist/check_123", text)
        self.assertNotIn("Compare app_ref:checklist/checklist/check_123", text)

    def test_app_reference_materialization_remains_supported(self) -> None:
        text = input_text_with_app_references(
            input_text="Ask @Chat to summarize this",
            app_references=[{"type": "app", "app_id": "chat", "label": "Chat"}],
        )

        self.assertIn("Ask app_id:chat to summarize this", text)
        self.assertIn("Referenced apps:\n- app_id: chat", text)


if __name__ == "__main__":
    unittest.main()
