from __future__ import annotations

import unittest

from core.api.provider_api import _compact_agentic_admin_items


def _item(revision: str, **overrides) -> dict[str, object]:
    item: dict[str, object] = {
        "definition_id": "codex:sol",
        "definition_revision": revision,
        "execution_family": "native_agent",
        "runtime_engine_id": "codex",
        "model_provider_id": "codex",
        "model_id": "gpt-5.6-sol",
        "binding": None,
        "selectable": False,
        "enable_eligible": False,
        "full_workspace_status": "unavailable",
    }
    item.update(overrides)
    return item


class ProviderAdminCompactionTestCase(unittest.TestCase):
    def test_keeps_one_naturally_latest_revision_per_visual_model(self) -> None:
        items = [_item("9"), _item("10"), _item("2")]

        self.assertEqual(_compact_agentic_admin_items(items), [items[1]])

    def test_prefers_enabled_default_over_newer_candidates(self) -> None:
        active = _item(
            "14",
            binding={"enabled": True, "is_default": True},
        )
        candidate = _item("15", selectable=True)

        self.assertEqual(
            _compact_agentic_admin_items([active, candidate]),
            [active],
        )

    def test_keeps_provider_model_and_execution_family_categories_distinct(self) -> None:
        items = [
            _item("15"),
            _item("15", model_provider_id="other"),
            _item("15", model_id="gpt-5.6-terra"),
            _item("15", execution_family="maverick_agent"),
        ]

        self.assertEqual(_compact_agentic_admin_items(items), items)

    def test_groups_legacy_codex_with_the_native_family(self) -> None:
        old = _item("3", execution_family=None)
        current = _item("15")

        self.assertEqual(_compact_agentic_admin_items([old, current]), [current])


if __name__ == "__main__":
    unittest.main()
