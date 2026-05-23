"""Frontend source smoke checks for CRM view-state behavior."""

from __future__ import annotations

from pathlib import Path
import unittest


APP_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx"
ROUTING_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "domain" / "routing.ts"
TYPES_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "domain" / "types.ts"
VIEW_MODEL_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "domain" / "viewModel.ts"
VIEWS_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "CrmViews.tsx"
RECORD_SIDE_PANEL_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "RecordSidePanel.tsx"
DETAIL_CSS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "detail.css"
SIDEBAR_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "crm-sidebar" / "main.tsx"
SIDEBAR_FOOTER_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "crm-sidebar-footer" / "main.tsx"
SIDEBAR_FOOTER_CSS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "crm-sidebar-footer" / "styles.css"


class CrmFrontendSourceTest(unittest.TestCase):
    def test_search_view_filter_is_rendered(self) -> None:
        app_source = APP_TSX.read_text(encoding="utf-8")
        view_model_source = VIEW_MODEL_TS.read_text(encoding="utf-8")
        views_source = VIEWS_TSX.read_text(encoding="utf-8")

        self.assertIn("viewFilter?.mode !== 'search'", app_source)
        self.assertIn("lastAppliedViewFilter.current", app_source)
        self.assertIn("const nextQuery = typeof viewFilter.query === 'string'", app_source)
        self.assertIn("setQuery(nextQuery)", app_source)
        self.assertIn("if (entityType !== 'all')", app_source)
        self.assertIn("searchEntityType !== 'all'", view_model_source)
        self.assertIn("setRecordEntityFilter(entityFilterForEntity(entityType))", app_source)
        self.assertIn("crm.records_table", app_source)
        self.assertIn("RecordsView", app_source)
        self.assertIn("const tableTitle = label ||", views_source)

    def test_primary_navigation_is_next_level_four_view_model(self) -> None:
        app_source = APP_TSX.read_text(encoding="utf-8")
        routing_source = ROUTING_TS.read_text(encoding="utf-8")
        types_source = TYPES_TS.read_text(encoding="utf-8")
        sidebar_source = SIDEBAR_TSX.read_text(encoding="utf-8")

        self.assertIn("type ViewId = 'records' | 'pipeline' | 'operations' | 'reports' | 'import'", types_source)
        self.assertIn("const recordEntityFilters", routing_source)
        self.assertIn("view === 'records'", app_source)
        self.assertIn("view === 'pipeline'", app_source)
        self.assertIn("view === 'operations'", app_source)
        self.assertIn("view === 'reports'", app_source)
        self.assertIn("{ label: 'Records', page: 'records'", sidebar_source)
        self.assertIn("{ label: 'Pipeline', page: 'pipeline'", sidebar_source)
        self.assertIn("{ label: 'Operations', page: 'operations'", sidebar_source)
        self.assertIn("{ label: 'Reports', page: 'reports'", sidebar_source)
        self.assertNotIn("label: 'Leads'", sidebar_source)
        self.assertNotIn("label: 'Accounts'", sidebar_source)
        self.assertNotIn("label: 'Contacts'", sidebar_source)
        self.assertNotIn("label: 'Import'", sidebar_source)

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

    def test_record_detail_uses_side_panel(self) -> None:
        app_source = APP_TSX.read_text(encoding="utf-8")
        side_panel_source = RECORD_SIDE_PANEL_TSX.read_text(encoding="utf-8")
        styles = DETAIL_CSS.read_text(encoding="utf-8")

        self.assertIn("RecordSidePanel", app_source)
        self.assertNotIn("RecordDetailModal", app_source)
        self.assertIn("crm-detail-drawer", side_panel_source)
        self.assertIn("crm-detail-side-panel", side_panel_source)
        self.assertIn('aria-modal="false"', side_panel_source)
        self.assertIn(".crm-detail-side-panel", styles)
        self.assertIn("grid-column: 2", styles)
        self.assertIn("height: 90dvh", styles)

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
