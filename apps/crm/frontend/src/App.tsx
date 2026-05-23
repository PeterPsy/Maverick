import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { BootstrapPayload, CrmRecord, PipelineStage, RecordsTablePayload, SavedView, callBackend } from './api';
import { CreateChooserModal, RecordComposerModal } from './views/RecordComposer';
import { RecordSidePanel } from './views/RecordSidePanel';
import { OperationsView, ReportsView, WorkspaceToolbar } from './views/CrmViews';
import { ImportPanel } from './views/ImportPanel';
import { Pipeline } from './views/PipelineView';
import { RecordsView } from './views/RecordsView';
import { ComposerState, ImportPreview, MutatedRecordPayload, PendingSelection, RecordEntityFilter, SalesReportsPayload, ViewId, emptyPayload } from './domain/types';
import { buildCrmViewModel } from './domain/viewModel';
import { createActions, entityFilterForEntity, isCreatableEntity, parseColumnMapping, updateActions, viewForEntity, viewFromAppPage } from './domain/routing';

export function App() {
  const [view, setView] = useState<ViewId>('records');
  const [recordEntityFilter, setRecordEntityFilter] = useState<RecordEntityFilter>('all');
  const [recordsCursor, setRecordsCursor] = useState('');
  const [recordsCursorHistory, setRecordsCursorHistory] = useState<string[]>([]);
  const [recordsSort, setRecordsSort] = useState({ field: 'updated_at', direction: 'desc' });
  const [recordsData, setRecordsData] = useState<RecordsTablePayload | null>(null);
  const [reports, setReports] = useState<SalesReportsPayload | null>(null);
  const [data, setData] = useState<BootstrapPayload>(emptyPayload);
  const [selected, setSelected] = useState<{ entity: string; record: CrmRecord } | null>(null);
  const [composer, setComposer] = useState<ComposerState>(null);
  const [isCreateChooserOpen, setIsCreateChooserOpen] = useState(false);
  const [pendingSelection, setPendingSelection] = useState<PendingSelection>(null);
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [bulkSelection, setBulkSelection] = useState<Set<string>>(new Set());
  const [error, setError] = useState('');
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const lastAppliedViewFilter = useRef('');

  async function refresh() {
    setIsLoading(true);
    setError('');
    try {
      setData(await callBackend<BootstrapPayload>({ action: 'bootstrap' }));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load CRM data.');
    } finally {
      setIsLoading(false);
    }
  }

  async function refreshRecords(cursor = recordsCursor) {
    setError('');
    try {
      setRecordsData(await callBackend<RecordsTablePayload>({
        action: 'crm.records_table',
        entity_type: recordEntityFilter,
        query,
        filters,
        sort: recordsSort,
        pagination: { limit: 50, cursor }
      }));
    } catch (recordsError) {
      setError(recordsError instanceof Error ? recordsError.message : 'Unable to load CRM records.');
    }
  }

  async function refreshReports() {
    setError('');
    try {
      setReports(await callBackend<SalesReportsPayload>({ action: 'crm.sales_reports' }));
    } catch (reportsError) {
      setError(reportsError instanceof Error ? reportsError.message : 'Unable to load CRM reports.');
    }
  }

  useEffect(() => {
    void refresh();
    function handleMessage(event: MessageEvent) {
      if (event.origin === window.location.origin && event.data?.type === 'maverick.app.data-changed' && event.data?.owner_app_id === 'crm') {
        void refresh();
      }
      if (event.origin === window.location.origin && event.data?.type === 'maverick.app.navigate') {
        const params = event.data.params && typeof event.data.params === 'object' ? event.data.params : {};
        const appPage = typeof params.app_page === 'string' ? params.app_page : typeof event.data.app_page === 'string' ? event.data.app_page : '';
        const intent = typeof params.intent === 'string' ? params.intent : '';
        if (intent === 'create-menu') {
          setSelected(null);
          setComposer(null);
          setIsCreateChooserOpen(true);
          return;
        }
        if (intent === 'create' && isCreatableEntity(params.entity_type)) {
          setSelected(null);
          setIsCreateChooserOpen(false);
          setView(viewForEntity(params.entity_type));
          setRecordEntityFilter(entityFilterForEntity(params.entity_type));
          setComposer({ mode: 'create', entity: params.entity_type });
          return;
        }
        const navigation = viewFromAppPage(appPage);
        setView(navigation.view);
        setRecordEntityFilter(navigation.entityFilter);
        setPendingSelection(navigation.selection);
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  useEffect(() => {
    setRecordsCursor('');
    setRecordsCursorHistory([]);
  }, [recordEntityFilter, query, filters, recordsSort]);

  useEffect(() => {
    if (view === 'records') {
      void refreshRecords(recordsCursor);
    }
    if (view === 'reports') {
      void refreshReports();
    }
  }, [view, recordEntityFilter, query, filters, recordsSort, recordsCursor]);

  useEffect(() => {
    if (!pendingSelection) return;
    const recordsByEntity: Record<string, CrmRecord[]> = {
      lead: data.leads,
      account: data.accounts,
      contact: data.contacts,
      deal: data.deals,
      activity: data.activities,
      task: data.tasks,
      note: data.notes
    };
    const record = recordsByEntity[pendingSelection.entity]?.find((item) => item.id === pendingSelection.id);
    if (record) {
      setSelected({ entity: pendingSelection.entity, record });
      setPendingSelection(null);
    }
  }, [data, pendingSelection]);

  useEffect(() => {
    if (!selected && !composer && !isCreateChooserOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        if (isCreateChooserOpen) {
          setIsCreateChooserOpen(false);
        } else if (composer) {
          setComposer(null);
        } else {
          setSelected(null);
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selected, composer, isCreateChooserOpen]);

  useEffect(() => {
    const viewFilter = data.view_state?.view_filter;
    if (viewFilter?.mode !== 'search') return;
    const entityType = typeof viewFilter.entity_type === 'string' ? viewFilter.entity_type : 'all';
    const nextQuery = typeof viewFilter.query === 'string' ? viewFilter.query : '';
    const signature = JSON.stringify({ mode: viewFilter.mode, entity_type: entityType, query: nextQuery });
    if (lastAppliedViewFilter.current === signature) return;
    lastAppliedViewFilter.current = signature;
    setQuery(nextQuery);
    if (entityType !== 'all') {
      setView('records');
      setRecordEntityFilter(entityFilterForEntity(entityType));
    }
  }, [data.view_state]);

  const viewModel = useMemo(() => buildCrmViewModel(data), [data]);

  useEffect(() => {
    setBulkSelection(new Set());
  }, [view]);

  async function saveComposer(state: Exclude<ComposerState, null>, values: Record<string, unknown>) {
    setIsSaving(true);
    setError('');
    try {
      const action = state.mode === 'create' ? createActions[state.entity] : updateActions[state.entity];
      const body = state.mode === 'edit' ? { ...values, id: state.record.id } : values;
      await callBackend({ action, ...body });
      setView(viewForEntity(state.entity));
      setRecordEntityFilter(entityFilterForEntity(state.entity));
      setComposer(null);
      await refresh();
      await refreshRecords('');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Unable to save record.');
    } finally {
      setIsSaving(false);
    }
  }

  async function clearCustomView() {
    setIsSaving(true);
    setError('');
    try {
      await callBackend({ action: 'crm.clear_custom_view' });
      await refresh();
    } catch (clearError) {
      setError(clearError instanceof Error ? clearError.message : 'Unable to clear custom view.');
    } finally {
      setIsSaving(false);
    }
  }

  async function saveCurrentView() {
    const title = window.prompt('Saved view name');
    if (!title?.trim()) return;
    setIsSaving(true);
    setError('');
    try {
      const entityType = view === 'records' ? recordEntityFilter : 'all';
      await callBackend({ action: 'crm.save_view', title: title.trim(), entity_type: entityType, query, filters });
      await refresh();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Unable to save view.');
    } finally {
      setIsSaving(false);
    }
  }

  async function applySavedView(savedView: SavedView) {
    setIsSaving(true);
    setError('');
    try {
      await callBackend({ action: 'crm.apply_saved_view', id: savedView.id });
      setFilters(Object.fromEntries(Object.entries(savedView.filters || {}).map(([key, value]) => [key, String(value)])));
      await refresh();
    } catch (applyError) {
      setError(applyError instanceof Error ? applyError.message : 'Unable to apply saved view.');
    } finally {
      setIsSaving(false);
    }
  }

  async function mutateSelectedRecord(action: string, extras: Record<string, unknown> = {}, closeAfter = false) {
    if (!selected) return;
    setIsSaving(true);
    setError('');
    try {
      const result = await callBackend<MutatedRecordPayload>({
        action,
        entity_type: selected.entity,
        id: selected.record.id,
        ...extras
      });
      if (closeAfter) {
        setSelected(null);
      } else if (result.record) {
        setSelected({ entity: selected.entity, record: result.record });
      }
      await refresh();
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : 'Unable to update record.');
    } finally {
      setIsSaving(false);
    }
  }

  async function tagSelectedRecord() {
    const tag = window.prompt('Tag');
    if (!tag?.trim()) return;
    await mutateSelectedRecord('crm.tag_record', { tag: tag.trim() });
  }

  async function convertSelectedLead() {
    if (!selected || selected.entity !== 'lead') return;
    setIsSaving(true);
    setError('');
    try {
      await callBackend({ action: 'crm.convert_lead', lead_id: selected.record.id });
      setSelected(null);
      await refresh();
    } catch (convertError) {
      setError(convertError instanceof Error ? convertError.message : 'Unable to convert lead.');
    } finally {
      setIsSaving(false);
    }
  }

  async function moveDeal(dealId: string, stageId: string) {
    setIsSaving(true);
    setError('');
    try {
      await callBackend({ action: 'crm.move_deal', id: dealId, stage_id: stageId });
      await refresh();
    } catch (moveError) {
      setError(moveError instanceof Error ? moveError.message : 'Unable to move deal.');
    } finally {
      setIsSaving(false);
    }
  }

  async function configureStage(stage?: PipelineStage) {
    const name = window.prompt('Stage name', stage?.name || '');
    if (!name?.trim()) return;
    const probabilityText = window.prompt('Probability 0-1', String(stage?.probability ?? 0.5));
    if (probabilityText === null) return;
    setIsSaving(true);
    setError('');
    try {
      await callBackend({
        action: stage ? 'crm.update_pipeline_stage' : 'crm.create_pipeline_stage',
        id: stage?.id,
        pipeline_id: stage?.pipeline_id || 'pipeline_default',
        name: name.trim(),
        position: stage?.position,
        probability: Number(probabilityText)
      });
      await refresh();
    } catch (stageError) {
      setError(stageError instanceof Error ? stageError.message : 'Unable to save pipeline stage.');
    } finally {
      setIsSaving(false);
    }
  }

  async function runBulk(operation: 'archive' | 'delete' | 'tag') {
    const idsByEntity = [...bulkSelection].reduce<Record<string, string[]>>((accumulator, key) => {
      const [entity, id] = key.split(':');
      accumulator[entity] = [...(accumulator[entity] || []), id];
      return accumulator;
    }, {});
    const tag = operation === 'tag' ? window.prompt('Tag selected records') : '';
    if (operation === 'tag' && !tag?.trim()) return;
    setIsSaving(true);
    setError('');
    try {
      for (const [entityType, ids] of Object.entries(idsByEntity)) {
        await callBackend({ action: 'crm.bulk_update', entity_type: entityType, ids, operation, tag });
      }
      setBulkSelection(new Set());
      await refresh();
    } catch (bulkError) {
      setError(bulkError instanceof Error ? bulkError.message : 'Bulk action failed.');
    } finally {
      setIsSaving(false);
    }
  }

  async function deleteSelectedRecord() {
    if (!window.confirm('Delete this CRM record?')) return;
    await mutateSelectedRecord('crm.delete_record', {}, true);
  }

  async function handleImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const action = submitter?.name === 'preview' ? 'crm.import_preview' : 'crm.import_commit';
    setIsSaving(true);
    setError('');
    try {
      const result = await callBackend<ImportPreview>({
        action,
        entity_type: form.get('entity_type'),
        csv: form.get('csv'),
        column_mapping: parseColumnMapping(form.get('column_mapping'))
      });
      if (action === 'crm.import_preview') {
        setImportPreview(result);
      } else {
        setImportPreview(null);
        event.currentTarget.reset();
        await refresh();
      }
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : 'Import failed.');
    } finally {
      setIsSaving(false);
    }
  }

  function goToNextRecordsPage() {
    if (!recordsData?.next_cursor) return;
    setRecordsCursorHistory((history) => [...history, recordsCursor]);
    setRecordsCursor(recordsData.next_cursor);
  }

  function goToPreviousRecordsPage() {
    setRecordsCursorHistory((history) => {
      const nextHistory = [...history];
      const previous = nextHistory.pop() || '';
      setRecordsCursor(previous);
      return nextHistory;
    });
  }

  return (
    <main className="crm-app">
      <section className="crm-workspace">
        {error ? <div className="crm-alert">{error}</div> : null}
        {viewModel.isCustom ? (
          <div className="crm-view-banner">
            <span>{viewModel.title}</span>
            <strong>{viewModel.all.length} records</strong>
            <button onClick={clearCustomView} disabled={isSaving}>Clear</button>
          </div>
        ) : null}
        <WorkspaceToolbar
          filters={filters}
          savedViews={data.saved_views || []}
          selectedCount={bulkSelection.size}
          onApplySavedView={applySavedView}
          onBulkArchive={() => runBulk('archive')}
          onBulkTag={() => runBulk('tag')}
          onFilterChange={setFilters}
          onSaveView={saveCurrentView}
        />

        {view === 'records' ? (
          <RecordsView
            data={recordsData}
            entityFilter={recordEntityFilter}
            hasPrevious={recordsCursorHistory.length > 0}
            isLoading={isLoading && !recordsData}
            onEntityFilterChange={setRecordEntityFilter}
            onNextPage={goToNextRecordsPage}
            onPreviousPage={goToPreviousRecordsPage}
            onSelect={(item) => setSelected({ entity: item.entity_type, record: item.record })}
            onSort={(field) => setRecordsSort((current) => ({ field, direction: current.field === field && current.direction === 'desc' ? 'asc' : 'desc' }))}
            bulkSelection={bulkSelection}
            setBulkSelection={setBulkSelection}
          />
        ) : null}
        {view === 'pipeline' ? <Pipeline data={{ ...data, deals: viewModel.deals }} select={setSelected} onMoveDeal={moveDeal} onConfigureStage={configureStage} /> : null}
        {view === 'operations' ? <OperationsView data={{ ...data, tasks: viewModel.tasks }} select={setSelected} /> : null}
        {view === 'reports' ? <ReportsView reports={reports} isLoading={isLoading && !reports} /> : null}
        {view === 'import' ? <ImportPanel onSubmit={handleImport} isSaving={isSaving} preview={importPreview} /> : null}
      </section>

      {selected ? (
        <RecordSidePanel
          selected={selected}
          isSaving={isSaving}
          onClose={() => setSelected(null)}
          onEdit={(entity, record) => {
            if (!isCreatableEntity(entity)) return;
            setSelected(null);
            setComposer({ mode: 'edit', entity, record });
          }}
          onArchive={() => mutateSelectedRecord('crm.archive_record', {}, true)}
          onDelete={deleteSelectedRecord}
          onTag={tagSelectedRecord}
          onConvertLead={convertSelectedLead}
        />
      ) : null}
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
      {composer ? <RecordComposerModal state={composer} data={data} isSaving={isSaving} onClose={() => setComposer(null)} onSubmit={(values) => saveComposer(composer, values)} /> : null}
    </main>
  );
}
