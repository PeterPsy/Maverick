import { TasksWorkspace } from './views/workspace/TasksWorkspace';
import { RelationshipsWorkspace } from './views/workspace/RelationshipsWorkspace';
import { ContextWorkspace } from './views/workspace/ContextWorkspace';
import { ExpensesWorkspace } from './views/workspace/ExpensesWorkspace';
import { CalendarWorkspace } from './views/workspace/CalendarWorkspace';
import { QualityWorkspace, ProposalsWorkspace, TranscriptsWorkspace } from './views/workspace/ReviewWorkspace';
import { RecordInspector } from './views/workspace/RecordInspector';
import { ExtensionDetail } from './views/ExtensionDetail';
import { ExtensionList } from './views/ExtensionList';
import { OverviewView } from './views/OverviewView';
import { IntegrationsView } from './views/IntegrationsView';
import { extensionPages, extensionEntities } from './domain/vnext';
import { ViewId } from './domain/types';
import { ActionDialog, ActionDialogValues } from './views/ActionDialogs';
import { CreateChooserModal, RecordComposerModal } from './views/RecordComposer';
import { RecordSidePanel } from './views/RecordSidePanel';
import { WorkspaceTopbar } from './views/CrmViews';
import { ImportPanel } from './views/ImportPanel';
import { PipelineOperationsDeck } from './views/OperationsView';
import { Pipeline } from './views/PipelineView';
import { RecordsView } from './views/RecordsView';
import { ReportsView } from './views/ReportsView';
import { entityFilterForEntity, isCreatableEntity, viewForEntity } from './domain/routing';
import { useCrmActions } from './domain/useCrmActions';
import { useCrmDataController } from './domain/useCrmDataController';
import { PublicNavigation } from './public/PublicNavigation';
import { isPublicCrm, publicAccess } from './public/context';

export function App() {
  const crm = useCrmDataController();
  const actions = useCrmActions(crm);
  const {
    actionDialog,
    bulkSelection,
    composer,
    data,
    error,
    filters,
    importPreview,
    isCreateChooserOpen,
    isLoading,
    isSaving,
    pipelineBoard,
    query,
    recordEntityFilter,
    recordsCursorHistory,
    recordsData,
    recordsPageSize,
    reports,
    selected,
    setActionDialog,
    setBulkSelection,
    setComposer,
    setFilters,
    setIsCreateChooserOpen,
    setQuery,
    setRecordEntityFilter,
    setRecordsPageSize,
    setRecordsSort,
    setSelected,
    setView,
    view,
    viewModel
  } = crm;

  async function submitActionDialog(values: ActionDialogValues) {
    if (actionDialog?.kind === 'save-view') return actions.submitSavedView(values.title || '');
    if (actionDialog?.kind === 'record-tag') return actions.submitRecordTag(values.tag || '');
    if (actionDialog?.kind === 'bulk-tag') return actions.submitBulkTag(values.tag || '');
    if (actionDialog?.kind === 'pipeline-stage') return actions.submitPipelineStage({ name: values.name || '', probability: Number(values.probability ?? 0.5) });
    return false;
  }

  function openStageReport(stage: string) {
    setSelected(null);
    setRecordEntityFilter('deal');
    setFilters({ status: stage });
    setView('records');
  }

  function openAgentDeckReport(nextFilters: Record<string, string>) {
    setSelected(null);
    setFilters(nextFilters);
    setView('pipeline');
  }

  function openDealReport(record: { id?: string } & Record<string, unknown>) {
    if (!record.id) return;
    const fullRecord = viewModel.deals.find((deal) => deal.id === record.id) || record;
    setView('records');
    setRecordEntityFilter('deal');
    setSelected({ entity: 'deal', record: fullRecord as typeof viewModel.deals[number] });
  }

  function navigate(page: ViewId) { setSelected(null); setView(page); }
  function refreshWorkspace() { void crm.refresh(); }
  function closeInspector() { setSelected(null); window.dispatchEvent(new Event('crm-workspace-refresh')); }

  return (
    <main className={`crm-app product-shell ${selected ? 'is-showing-detail' : ''} ${isPublicCrm ? 'crm-public' : ''}`}>
      {isPublicCrm && <PublicNavigation view={view} navigate={navigate} />}
      <section className="crm-workspace product-main">
        {isPublicCrm && <div className="crm-public-notice" role="status">CRM pubblico · {publicAccess === 'read-only' ? 'Sola lettura: le modifiche sono disabilitate.' : 'Modificabile da chiunque abbia il link.'} Le integrazioni con altre app restano private.</div>}
        <WorkspaceTopbar
          onRefresh={refreshWorkspace}
          onCreate={() => setIsCreateChooserOpen(true)}
          query={query}
          selectedCount={selected ? 0 : bulkSelection.size}
          onBulkArchive={() => actions.runBulk('archive')}
          onBulkTag={() => actions.runBulk('tag')}
          onQueryChange={(value) => { setQuery(value); if (value && ['overview', 'integrations', 'reports'].includes(view)) navigate('records'); }}
        />
        <>
            {error ? <div className="crm-alert">{error}</div> : null}
            {viewModel.isCustom ? (
              <div className="crm-view-banner">
                <span>{viewModel.title}</span>
                <strong>{viewModel.all.length} records</strong>
                <button onClick={actions.clearCustomView} disabled={isSaving}>Clear</button>
              </div>
            ) : null}

            {view === 'overview' ? <OverviewView select={setSelected} navigate={navigate} createTask={() => setComposer({ mode: 'create', entity: 'task' })} /> : null}
            {['campaigns', 'objects'].includes(view) && extensionPages[view] ? <ExtensionList key={view} page={view} query={query} select={setSelected} /> : null}
            {view === 'today' ? <TasksWorkspace query={query} select={setSelected} create={() => setComposer({ mode: 'create', entity: 'task' })} /> : null}
            {['people', 'companies', 'deals'].includes(view) ? <RelationshipsWorkspace key={view} entity={view === 'people' ? 'contact' : view === 'companies' ? 'account' : 'deal'} query={query} select={setSelected} create={(entity) => setComposer({ mode: 'create', entity })} navigate={navigate} stages={data.pipeline_stages} /> : null}
            {view === 'conversations' || view === 'intelligence' || view === 'briefs' ? <ContextWorkspace key={view} page={view} query={query} select={setSelected} /> : null}
            {view === 'expenses' ? <ExpensesWorkspace query={query} select={setSelected} /> : null}
            {view === 'calendar' ? <CalendarWorkspace query={query} select={setSelected} /> : null}
            {view === 'quality' ? <QualityWorkspace query={query} select={setSelected} navigate={navigate} /> : null}
            {view === 'proposals' ? <ProposalsWorkspace query={query} select={setSelected} /> : null}
            {view === 'transcripts' ? <TranscriptsWorkspace query={query} select={setSelected} /> : null}
            {view === 'integrations' ? <IntegrationsView /> : null}
            {view === 'records' || view === 'leads' ? (
              <RecordsView
                data={recordsData}
                entityFilter={recordEntityFilter}
                hasPrevious={recordsCursorHistory.length > 0}
                isLoading={isLoading && !recordsData}
                currentPage={recordsCursorHistory.length + 1}
                pageSize={recordsPageSize}
                onEntityFilterChange={setRecordEntityFilter}
                onPageChange={actions.goToRecordsPage}
                onPageSizeChange={setRecordsPageSize}
                onNextPage={actions.goToNextRecordsPage}
                onPreviousPage={actions.goToPreviousRecordsPage}
                onSelect={(item) => setSelected({ entity: item.entity_type, record: item.record })}
                onSort={(field) => setRecordsSort((current) => ({ field, direction: current.field === field && current.direction === 'desc' ? 'asc' : 'desc' }))}
                bulkSelection={bulkSelection}
                setBulkSelection={setBulkSelection}
              />
            ) : null}
            {view === 'pipeline' ? (
              <section className="pipeline-command-center">
                <PipelineOperationsDeck
                  data={data}
                  filters={filters}
                  select={setSelected}
                  onWorkflowProposalAction={actions.reviewWorkflowProposal}
                  onWorkflowProposalPreview={actions.previewWorkflowProposal}
                  onDuplicateMerge={crm.refresh}
                />
                <Pipeline data={{ ...data, deals: viewModel.deals }} board={pipelineBoard} select={setSelected} onDeleteStage={actions.deletePipelineStage} onMoveDeal={actions.moveDeal} onConfigureStage={actions.configureStage} />
              </section>
            ) : null}
            {view === 'reports' ? (
              <ReportsView
                reports={reports}
                isLoading={isLoading && !reports}
                onOpenStage={openStageReport}
                onOpenDeal={openDealReport}
                onOpenAgentDeck={openAgentDeckReport}
              />
            ) : null}
            {view === 'import' ? <ImportPanel onSubmit={actions.handleImport} isSaving={isSaving} preview={importPreview} /> : null}
          </>
      </section>
      {selected ? <RecordInspector recordKey={`${selected.entity}:${selected.record.id}`}>
        {selected && extensionEntities.includes(selected.entity) ? <ExtensionDetail key={`${selected.entity}:${selected.record.id}`} selected={selected} select={setSelected} onClose={closeInspector} /> : selected ? (
          <RecordSidePanel
            selected={selected}
            onSelectRelated={setSelected}
            isSaving={isSaving}
            onClose={closeInspector}
            onEdit={(entity, record) => {
              if (!isCreatableEntity(entity)) return;
              setSelected(null);
              setComposer({ mode: 'edit', entity, record });
            }}
            onArchive={actions.archiveSelectedRecord}
            onDelete={actions.deleteSelectedRecord}
            onTag={actions.tagSelectedRecord}
            onConvertLead={actions.convertSelectedLead}
          />
        ) : null}
      </RecordInspector> : null}
      {isCreateChooserOpen ? (
        <CreateChooserModal
          onClose={() => setIsCreateChooserOpen(false)}
          onChoose={(entity) => {
            setIsCreateChooserOpen(false);
            setView(viewForEntity(entity));
            setRecordEntityFilter(entityFilterForEntity(entity));
            setComposer({ mode: 'create', entity });
          }}
        />
      ) : null}
      {composer ? <RecordComposerModal state={composer} data={data} isSaving={isSaving} onClose={() => setComposer(null)} onSubmit={(values) => actions.saveComposer(composer, values)} /> : null}
      <ActionDialog dialog={actionDialog} isSaving={isSaving} onClose={() => setActionDialog(null)} onSubmit={submitActionDialog} />
    </main>
  );
}
