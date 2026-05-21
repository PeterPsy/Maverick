"""Frontend source smoke checks for CRM view-state behavior."""

from __future__ import annotations

from pathlib import Path
import unittest


APP_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx"
SIDEBAR_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "crm-sidebar" / "main.tsx"
SIDEBAR_FOOTER_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "crm-sidebar-footer" / "main.tsx"
SIDEBAR_FOOTER_CSS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "crm-sidebar-footer" / "styles.css"


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

    def test_custom_view_and_create_intent_are_rendered(self) -> None:
        source = APP_TSX.read_text(encoding="utf-8")

        self.assertIn("intent === 'create'", source)
        self.assertIn("intent === 'create-menu'", source)
        self.assertIn("CreateChooserModal", source)
        self.assertIn("isCreatableEntity(params.entity_type)", source)
        self.assertIn("setComposer({ mode: 'create', entity: params.entity_type })", source)
        self.assertIn("RecordComposerModal", source)
        self.assertNotIn("quickCreate", source)
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

    def test_sidebar_footer_uses_primary_action_protocol(self) -> None:
        source = SIDEBAR_FOOTER_TSX.read_text(encoding="utf-8")

        self.assertIn("crm-sidebar-footer-root", source)
        self.assertIn("maverick.widget.open-app", source)
        self.assertIn("intent: 'create-menu'", source)
        self.assertIn("create_menu_request_id: crypto.randomUUID()", source)
        self.assertIn("maverick.widget.primary-action.state", source)
        self.assertIn("maverick.widget.primary-action.query", source)
        self.assertIn("maverick.widget.primary-action.invoke", source)
        self.assertIn("widget_id: WIDGET_ID", source)
        self.assertIn("crm-add-button", source)

    def test_sidebar_footer_does_not_render_clipped_dropdown(self) -> None:
        source = SIDEBAR_FOOTER_TSX.read_text(encoding="utf-8")
        styles = SIDEBAR_FOOTER_CSS.read_text(encoding="utf-8")

        self.assertNotIn("crm-create-menu", source)
        self.assertNotIn("crm-create-menu", styles)
        self.assertNotIn("position: absolute", styles)
        self.assertIn("height: 100%", styles)
        self.assertIn("min-height: 2.65rem", styles)


if __name__ == "__main__":
    unittest.main()
