"""Frontend source smoke checks for CRM view-state behavior."""

from __future__ import annotations

from pathlib import Path
import unittest


APP_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx"
SIDEBAR_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "crm-sidebar" / "main.tsx"


class CrmFrontendSourceTest(unittest.TestCase):
    def test_search_view_filter_is_rendered(self) -> None:
        source = APP_TSX.read_text(encoding="utf-8")

        self.assertIn("viewFilter?.mode !== 'search'", source)
        self.assertIn("lastAppliedViewFilter.current", source)
        self.assertIn("const nextQuery = typeof viewFilter.query === 'string'", source)
        self.assertIn("setQuery(nextQuery)", source)
        self.assertIn("if (entityType !== 'all')", source)
        self.assertIn("searchEntityType !== 'all'", source)
        self.assertIn("activities: 'activity'", source)
        self.assertIn("activity: 'activities'", source)
        self.assertIn('entity="activity" label="Activities"', source)
        self.assertIn("const tableTitle = label ||", source)

    def test_custom_view_and_widget_intent_are_rendered(self) -> None:
        source = APP_TSX.read_text(encoding="utf-8")

        self.assertIn("intent === 'new-contact'", source)
        self.assertIn("void quickCreate('contact')", source)
        self.assertIn("crm-view-banner", source)
        self.assertIn("crm.clear_custom_view", source)
        self.assertIn("activity: data.activities", source)

    def test_search_lives_in_sidebar_not_full_app_toolbar(self) -> None:
        app_source = APP_TSX.read_text(encoding="utf-8")
        sidebar_source = SIDEBAR_TSX.read_text(encoding="utf-8")

        self.assertNotIn("crm-toolbar", app_source)
        self.assertNotIn("crm-toolbar__actions", app_source)
        self.assertNotIn("RefreshCw", app_source)
        self.assertNotIn("<Plus", app_source)
        self.assertIn("crm-sidebar-search-frame", sidebar_source)
        self.assertIn("crm.set_view_filter", sidebar_source)


if __name__ == "__main__":
    unittest.main()
