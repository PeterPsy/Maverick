"""Tests for runtime turn input enrichment."""

from __future__ import annotations

import unittest

from core.runtime.turn_submission import input_text_with_app_references


class RuntimeTurnSubmissionTestCase(unittest.TestCase):
    def test_app_references_are_added_as_app_ids_for_provider_input(self) -> None:
        text = input_text_with_app_references(
            input_text="controlla @Chat e @gallery",
            app_references=[
                {"type": "app", "app_id": "chat", "label": "Chat"},
                {"type": "app", "app_id": "chat", "label": "Chat duplicate"},
                {"type": "app", "app_id": "gallery"},
            ],
        )

        self.assertEqual(
            text,
            "controlla app_id:chat e app_id:gallery\n\nReferenced apps:\n- app_id: chat\n- app_id: gallery",
        )


if __name__ == "__main__":
    unittest.main()
