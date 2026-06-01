"""Frontend source smoke checks for CRM view-state behavior."""

from __future__ import annotations

from pathlib import Path
import unittest


APP_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx"
ROUTING_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "domain" / "routing.ts"
TYPES_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "domain" / "types.ts"
VIEW_MODEL_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "domain" / "viewModel.ts"
DATA_CONTROLLER_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "domain" / "useCrmDataController.ts"
VIEW_ACTIONS_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "domain" / "useCrmViewActions.ts"
WORKFLOW_ACTIONS_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "domain" / "useCrmWorkflowActions.ts"
VIEWS_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "CrmViews.tsx"
OPERATIONS_VIEW_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "OperationsView.tsx"
RECORDS_VIEW_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "RecordsView.tsx"
RECORDS_TABLE_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "ui" / "records-table-with-modal.tsx"
RECORD_SIDE_PANEL_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "RecordSidePanel.tsx"
RECORD_SIDE_PANEL_SECTIONS_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "RecordSidePanelSections.tsx"
PIPELINE_VIEW_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "PipelineView.tsx"
DETAIL_CSS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "detail.css"
RECORDS_CSS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "records.css"
SIDEBAR_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "crm-sidebar" / "main.tsx"


class CrmFrontendSourceTest(unittest.TestCase):
    def test_search_view_filter_is_rendered(self) -> None:
        app_source = APP_TSX.read_text(encoding="utf-8")
        controller_source = DATA_CONTROLLER_TS.read_text(encoding="utf-8")
        view_model_source = VIEW_MODEL_TS.read_text(encoding="utf-8")
        records_source = RECORDS_VIEW_TSX.read_text(encoding="utf-8")
        records_table_source = RECORDS_TABLE_TSX.read_text(encoding="utf-8")

        self.assertIn("viewFilter?.mode !== 'search'", controller_source)
        self.assertIn("lastAppliedViewFilter.current", controller_source)
        self.assertIn("const nextQuery = typeof viewFilter.query === 'string'", controller_source)
        self.assertIn("setQuery(nextQuery)", controller_source)
        self.assertIn("if (entityType !== 'all')", controller_source)
        self.assertIn("searchEntityType !== 'all'", view_model_source)
        self.assertIn("setRecordEntityFilter(entityFilterForEntity(entityType))", controller_source)
        self.assertIn("crm.records_table", controller_source)
        self.assertIn("RecordsView", app_source)
        self.assertIn('title="CRM records"', records_source)
        self.assertIn("<h2>{title}</h2>", records_table_source)
        self.assertIn('aria-label="Records pagination"', records_table_source)
        self.assertNotIn("<footer", records_table_source)
        self.assertNotIn("Object.entries(data?.counts", records_table_source)

    def test_records_table_renders_labels_and_custom_fields(self) -> None:
        records_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "RecordsView.tsx").read_text(encoding="utf-8")
        api_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
        records_table_source = RECORDS_TABLE_TSX.read_text(encoding="utf-8")

        self.assertIn("display?: Record<string, string>", api_source)
        self.assertIn("display.account || record.company", records_source)
        self.assertIn("display.contact || ''", records_source)
        self.assertIn("columnKey === 'account_id'", records_source)
        self.assertIn("columnKey === 'contact_id'", records_source)
        self.assertIn("columnKey.startsWith('custom:')", records_source)
        self.assertIn("customFieldValue(row, columnKey)", records_source)
        self.assertIn("columnKey === 'connections'", records_source)
        self.assertIn("ConnectionBadges", records_table_source)
        self.assertIn("widthForColumn(column, rows, renderValue)", records_table_source)
        self.assertIn("<colgroup>", records_table_source)
        self.assertIn("--records-table-content-width", records_table_source)

    def test_primary_navigation_is_next_level_four_view_model(self) -> None:
        app_source = APP_TSX.read_text(encoding="utf-8")
        routing_source = ROUTING_TS.read_text(encoding="utf-8")
        types_source = TYPES_TS.read_text(encoding="utf-8")
        sidebar_source = SIDEBAR_TSX.read_text(encoding="utf-8")

        self.assertIn("type ViewId = 'records' | 'pipeline' | 'reports' | 'import'", types_source)
        self.assertIn("const recordEntityFilters", routing_source)
        self.assertIn("view === 'records'", app_source)
        self.assertIn("view === 'pipeline'", app_source)
        self.assertIn("view === 'reports'", app_source)
        self.assertIn("{ label: 'Records', page: 'records'", sidebar_source)
        self.assertIn("{ label: 'Pipeline', page: 'pipeline'", sidebar_source)
        self.assertIn("{ label: 'Reports', page: 'reports'", sidebar_source)
        self.assertIn("route === 'operations'", routing_source)
        self.assertIn("return { view: 'pipeline'", routing_source)
        self.assertNotIn("label: 'Leads'", sidebar_source)
        self.assertNotIn("label: 'Accounts'", sidebar_source)
        self.assertNotIn("label: 'Contacts'", sidebar_source)
        self.assertNotIn("label: 'Import'", sidebar_source)

    def test_pipeline_renders_agent_deck_and_workflow_lifecycle(self) -> None:
        app_source = APP_TSX.read_text(encoding="utf-8")
        api_source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
        workflow_actions_source = WORKFLOW_ACTIONS_TS.read_text(encoding="utf-8")
        operations_source = OPERATIONS_VIEW_TSX.read_text(encoding="utf-8")

        self.assertIn("workflow_proposals?: WorkflowProposal[]", api_source)
        self.assertIn("PipelineOperationsDeck", operations_source)
        self.assertIn("pipeline-command-center", app_source)
        self.assertIn("agent-deck-grid", operations_source)
        self.assertIn("crm.operations_feed", operations_source)
        self.assertIn("operation-evidence", operations_source)
        self.assertIn("operationsFeedCount(operationsFeed, 'to_do'", operations_source)
        self.assertIn("operationsFeedFilters(filters)", operations_source)
        self.assertIn("toDoCardsFromFeed(feedByKey.to_do", operations_source)
        self.assertIn("crm.list_workflow_proposals", operations_source)
        self.assertIn("crm.audit_log", operations_source)
        self.assertIn("filters={filters}", app_source)
        self.assertIn("onWorkflowProposalAction={actions.reviewWorkflowProposal}", app_source)
        self.assertNotIn("view === 'operations'", app_source)
        self.assertNotIn("operations-tabs", operations_source)
        self.assertIn("crm.approve_workflow_proposal", workflow_actions_source)
        self.assertIn("crm.apply_workflow_proposal", workflow_actions_source)
        self.assertIn("crm.dismiss_workflow_proposal", workflow_actions_source)
        self.assertIn("crm.reject_workflow_proposal", workflow_actions_source)
        self.assertIn("title=\"Dismiss workflow proposal\"", operations_source)
        self.assertIn("title=\"Reject workflow proposal\"", operations_source)

    def test_custom_view_and_create_intent_are_rendered(self) -> None:
        app_source = APP_TSX.read_text(encoding="utf-8")
        controller_source = DATA_CONTROLLER_TS.read_text(encoding="utf-8")
        view_actions_source = VIEW_ACTIONS_TS.read_text(encoding="utf-8")

        self.assertIn("intent === 'create'", controller_source)
        self.assertIn("intent === 'create-menu'", controller_source)
        self.assertIn("CreateChooserModal", app_source)
        self.assertIn("isCreatableEntity(params.entity_type)", controller_source)
        self.assertIn("setComposer({ mode: 'create', entity: params.entity_type })", controller_source)
        self.assertIn("RecordComposerModal", app_source)
        self.assertNotIn("quickCreate", app_source)
        self.assertIn("crm-view-banner", app_source)
        self.assertIn("crm.clear_custom_view", view_actions_source)
        self.assertIn("activity: data.activities", controller_source)

    def test_record_detail_uses_workspace_page(self) -> None:
        app_source = APP_TSX.read_text(encoding="utf-8")
        records_table_source = RECORDS_TABLE_TSX.read_text(encoding="utf-8")
        side_panel_source = RECORD_SIDE_PANEL_TSX.read_text(encoding="utf-8")
        styles = DETAIL_CSS.read_text(encoding="utf-8")
        app_styles = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        records_styles = RECORDS_CSS.read_text(encoding="utf-8")

        self.assertIn("RecordSidePanel", app_source)
        self.assertIn("crm-app ${selected ? 'is-showing-detail' : ''}", app_source)
        self.assertNotIn("RecordDetailModal", app_source)
        self.assertNotIn("RecordDetailModal", records_table_source)
        self.assertNotIn("records-row-action", records_table_source)
        self.assertNotIn("records-row-action", records_styles)
        self.assertIn("is-showing-detail", app_source)
        self.assertIn("crm-detail-page", side_panel_source)
        self.assertIn('role="region"', side_panel_source)
        self.assertIn("detail-back-button", side_panel_source)
        self.assertIn("ConnectionSummarySection", side_panel_source)
        self.assertIn("connection_summary?: ConnectionSummary", side_panel_source)
        self.assertIn("crm.external_timeline", side_panel_source)
        self.assertIn("detail-secondary-actions", side_panel_source)
        self.assertIn('aria-label="More record actions"', side_panel_source)
        self.assertIn("<span>Edit record</span>", side_panel_source)
        self.assertIn("<span>Tag record</span>", side_panel_source)
        self.assertIn("<span>Archive record</span>", side_panel_source)
        self.assertIn("<span>Delete record</span>", side_panel_source)
        self.assertNotIn('aria-modal="false"', side_panel_source)
        self.assertIn(".crm-detail-page", styles)
        self.assertIn("overflow-y: auto", styles)
        self.assertIn(".crm-detail-page::-webkit-scrollbar", styles)
        self.assertIn(".detail-back-button", styles)
        self.assertIn(".detail-secondary-menu", styles)
        self.assertIn(".crm-workspace.is-showing-detail", app_styles)
        self.assertIn(".crm-app.is-showing-detail", app_styles)
        self.assertIn("height: 100%", app_styles)
        self.assertIn("height: 100dvh", app_styles)
        self.assertNotIn("grid-column: 2", styles)
        self.assertNotIn("height: 90dvh", styles)

    def test_detail_panel_uses_backend_summary_and_blocks_inherited_unlink(self) -> None:
        side_panel_source = RECORD_SIDE_PANEL_TSX.read_text(encoding="utf-8")
        sections_source = RECORD_SIDE_PANEL_SECTIONS_TSX.read_text(encoding="utf-8")
        linked_styles = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "detail-linked.css").read_text(encoding="utf-8")

        self.assertIn("connectionSummary", side_panel_source)
        self.assertIn("setConnectionSummary(result.connection_summary || null)", side_panel_source)
        self.assertIn("Inherited links can only be unlinked", side_panel_source)
        self.assertIn("summary={connectionSummary}", side_panel_source)
        self.assertIn("summary: ConnectionSummary | null", sections_source)
        self.assertIn("summary?.badges", sections_source)
        self.assertIn("ShieldAlert", sections_source)
        self.assertIn("originLabel(item)", sections_source)
        self.assertIn("isInheritedRef(item)", sections_source)
        self.assertIn("Inherited from", sections_source)
        self.assertIn(".linked-list .linked-origin.inherited", linked_styles)

    def test_manual_crm_controls_are_in_overflow_or_admin_mode(self) -> None:
        views_source = VIEWS_TSX.read_text(encoding="utf-8")
        pipeline_source = PIPELINE_VIEW_TSX.read_text(encoding="utf-8")
        pipeline_styles = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "pipeline.css").read_text(encoding="utf-8")

        self.assertIn("WorkspaceTopbar", views_source)
        self.assertIn('aria-label="Search CRM"', views_source)
        self.assertNotIn("Status or stage", views_source)
        self.assertNotIn("Saved views", views_source)
        self.assertIn("bulk-actions__menu", views_source)
        self.assertIn("Tag selected records", views_source)
        self.assertIn("Archive selected records", views_source)
        self.assertIn("pipeline-stage-actions", pipeline_source)
        self.assertIn("Pipeline admin actions", pipeline_source)
        self.assertIn("<span>Edit stage</span>", pipeline_source)
        self.assertIn("<span>Delete stage</span>", pipeline_source)
        self.assertIn("<span>Add stage</span>", pipeline_source)
        self.assertIn("display: flex", pipeline_styles)
        self.assertIn("overflow-x: auto", pipeline_styles)
        self.assertIn("min-height: 18rem", pipeline_styles)
        self.assertNotIn("grid-template-columns: repeat(5, minmax(11rem, 1fr))", pipeline_styles)

    def test_linked_refs_do_not_require_hidden_technical_fields(self) -> None:
        source = RECORD_SIDE_PANEL_SECTIONS_TSX.read_text(encoding="utf-8")

        self.assertIn("const hasReferenceTarget", source)
        self.assertIn("const isManualLinkDisabled", source)
        self.assertIn('placeholder="Title"', source)
        self.assertIn('placeholder="Date"', source)
        self.assertIn('placeholder="Summary"', source)
        self.assertIn('aria-disabled={isManualLinkDisabled}', source)
        self.assertNotIn('aria-label="Source app id" placeholder="App" value={linkDraft.source_app_id} onChange={(event) => setLinkDraft((draft) => ({ ...draft, source_app_id: event.target.value }))} required', source)
        self.assertNotIn('aria-label="Source entity type" placeholder="Type" value={linkDraft.source_entity_type} onChange={(event) => setLinkDraft((draft) => ({ ...draft, source_entity_type: event.target.value }))} required', source)
        self.assertNotIn('aria-label="Source entity id" placeholder="Record ID" value={linkDraft.source_entity_id} onChange={(event) => setLinkDraft((draft) => ({ ...draft, source_entity_id: event.target.value }))} required', source)
        self.assertIn("metadata.deep_link", source)
        self.assertIn("metadata.app_page", source)
        self.assertIn("value.startsWith('/app/')", source)
        self.assertIn("value.startsWith('https://')", source)
        self.assertNotIn("value.startsWith('http://')", source)
        self.assertNotIn("pageByApp", source)

    def test_actions_use_controlled_dialogs_not_browser_prompts(self) -> None:
        frontend_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (Path(__file__).resolve().parents[1] / "frontend" / "src").rglob("*")
            if path.suffix in {".ts", ".tsx"}
        )

        self.assertNotIn("window.prompt", frontend_sources)
        self.assertNotIn("prompt(", frontend_sources)
        self.assertIn("ActionDialog", frontend_sources)
        self.assertIn("actionDialog", frontend_sources)

    def test_search_lives_in_workspace_topbar_not_sidebar(self) -> None:
        app_source = APP_TSX.read_text(encoding="utf-8")
        sidebar_source = SIDEBAR_TSX.read_text(encoding="utf-8")
        controller_source = DATA_CONTROLLER_TS.read_text(encoding="utf-8")
        views_source = VIEWS_TSX.read_text(encoding="utf-8")

        self.assertNotIn("crm-toolbar", app_source)
        self.assertNotIn("crm-toolbar__actions", app_source)
        self.assertNotIn("RefreshCw", app_source)
        self.assertNotIn("<Plus", app_source)
        self.assertIn("WorkspaceTopbar", app_source)
        self.assertIn("crm-search", views_source)
        self.assertIn("setQuery", app_source)
        self.assertIn("crm.set_view_filter", controller_source)
        self.assertNotIn("crm-sidebar-search-frame", sidebar_source)
        self.assertNotIn("crm.set_view_filter", sidebar_source)

if __name__ == "__main__":
    unittest.main()
