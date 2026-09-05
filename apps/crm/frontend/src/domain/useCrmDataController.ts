import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { readCrmDisplay } from '../pwaCache';
import { useEffect, useMemo, useRef, useState } from 'react';
import { BootstrapPayload, CrmRecord, PipelineBoardPayload, RecordsTablePayload, callBackend } from '../api';
import { buildCrmViewModel } from './viewModel';
import { ActionDialogState, ComposerState, ImportPreview, PendingSelection, RecordEntityFilter, SalesReportsPayload, ViewId, emptyPayload } from './types';
import { entityFilterForEntity, isCreatableEntity, viewForEntity, viewFromAppPage } from './routing';

export function useCrmDataController() {
  const [view, setView] = useState<ViewId>('records');
  const [recordEntityFilter, setRecordEntityFilter] = useState<RecordEntityFilter>('all');
  const [recordsCursor, setRecordsCursor] = useState('');
  const [recordsCursorHistory, setRecordsCursorHistory] = useState<string[]>([]);
  const [recordsPageSize, setRecordsPageSize] = useState(50);
  const [recordsSort, setRecordsSort] = useState({ field: 'updated_at', direction: 'desc' });
  const [recordsData, setRecordsData] = useState<RecordsTablePayload | null>(null);
  const [reports, setReports] = useState<SalesReportsPayload | null>(null);
  const [pipelineBoard, setPipelineBoard] = useState<PipelineBoardPayload | null>(null);
  const [data, setData] = useState<BootstrapPayload>(emptyPayload);
  const [selected, setSelected] = useState<{ entity: string; record: CrmRecord } | null>(null);
  const [composer, setComposer] = useState<ComposerState>(null);
  const [actionDialog, setActionDialog] = useState<ActionDialogState>(null);
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
  const lastPersistedSearchFilter = useRef(JSON.stringify({ query: '', entity_type: 'all' }));
  const hasLoadedSearchFilter = useRef(false);
  const cacheReads = useRef(new Map<string, AbortController>());
  const [recordsLoading, setRecordsLoading] = useState(true);
  async function displayRead<T>(slot: string, parameters: Record<string, unknown>, apply: (data: T) => void) {
    cacheReads.current.get(slot)?.abort();
    const controller = new AbortController();
    cacheReads.current.set(slot, controller);
    const current = () => !controller.signal.aborted;
    const update = (data: T) => { if (current()) apply(data); };
    const value = await readCrmDisplay<T>(parameters, {
      signal: controller.signal, onRevalidated: update,
      onRevalidationError: (error) => { if (current()) setError(error instanceof Error ? error.message : 'CRM read failed.'); },
    });
    update(value);
    return controller;
  }
  useEffect(() => () => { for (const controller of cacheReads.current.values()) controller.abort(); }, []);

  async function refresh() {
    setIsLoading(true);
    setError('');
    try {
      const controller = await displayRead<Partial<BootstrapPayload>>('bootstrap', { kind: 'bootstrap' }, (value) => setData((current) => ({ ...current, ...value })));
      // Workflow proposals, saved filters and other live-only surfaces are not
      // cached and never gate paint of the customer display projection.
      void callBackend<BootstrapPayload>({ action: 'bootstrap' }).then((value) => {
        if (!controller.signal.aborted) setData(value);
      }).catch(() => undefined);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load CRM data.');
    } finally {
      setIsLoading(false);
    }
  }

  async function refreshRecords(cursor = recordsCursor) {
    setError('');
    try {
      setRecordsLoading(true);
      await displayRead<RecordsTablePayload>('records', {
        kind: 'records_table', entity_type: recordEntityFilter, query, filters,
        sort_field: recordsSort.field, sort_direction: recordsSort.direction,
        limit: recordsPageSize, cursor,
      }, setRecordsData);
    } catch (recordsError) {
      if (!(recordsError instanceof Error && recordsError.name === 'AbortError')) setError(recordsError instanceof Error ? recordsError.message : 'Unable to load CRM records.');
    } finally { setRecordsLoading(false); }
  }

  async function refreshReports() {
    setError('');
    try {
      setReports(await callBackend<SalesReportsPayload>({ action: 'crm.sales_reports' }));
    } catch (reportsError) {
      setError(reportsError instanceof Error ? reportsError.message : 'Unable to load CRM reports.');
    }
  }

  async function refreshPipelineBoard() {
    try {
      await displayRead<PipelineBoardPayload>('pipeline', { kind: 'pipeline_board' }, setPipelineBoard);
    } catch {
      setPipelineBoard(null);
    }
  }

  useEffect(() => {
    void refresh();
    function handleMessage(event: MessageEvent) {
      if (isExactMaverickParentMessage(event) && event.data?.type === 'maverick.app.data-changed' && event.data?.owner_app_id === 'crm') {
        void refresh();
        void refreshPipelineBoard();
        void refreshRecords();
      }
      if (isExactMaverickParentMessage(event) && event.data?.type === 'maverick.app.navigate') {
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
  }, [recordEntityFilter, query, filters, recordsSort, recordsPageSize]);

  useEffect(() => {
    if (view === 'records') {
      void refreshRecords(recordsCursor);
    }
    if (view === 'reports') {
      void refreshReports();
    }
    if (view === 'pipeline') {
      void refreshPipelineBoard();
    }
  }, [view, recordEntityFilter, query, filters, recordsSort, recordsCursor, recordsPageSize]);

  useEffect(() => {
    const target = pendingSelection ?? (selected ? { entity: selected.entity, id: selected.record.id } : null);
    if (!target) return;
    void displayRead<{ record: CrmRecord }>('detail', { kind: 'get', entity_type: target.entity, id: target.id }, (value) => {
      setSelected({ entity: target.entity, record: value.record });
      setPendingSelection(null);
    }).catch((error: unknown) => { if (!(error instanceof Error && error.name === 'AbortError')) setError(error instanceof Error ? error.message : 'CRM detail failed.'); });
    return () => { cacheReads.current.get('detail')?.abort(); };
  }, [pendingSelection?.id, pendingSelection?.entity, selected?.record.id, selected?.entity]);

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
    if (!selected && !composer && !isCreateChooserOpen && !actionDialog) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        if (isCreateChooserOpen) {
          setIsCreateChooserOpen(false);
        } else if (actionDialog) {
          setActionDialog(null);
        } else if (composer) {
          setComposer(null);
        } else {
          setSelected(null);
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selected, composer, isCreateChooserOpen, actionDialog]);

  useEffect(() => {
    const viewFilter = data.view_state?.view_filter;
    if (viewFilter?.mode !== 'search') return;
    const entityType = typeof viewFilter.entity_type === 'string' ? viewFilter.entity_type : 'all';
    const nextQuery = typeof viewFilter.query === 'string' ? viewFilter.query : '';
    const signature = JSON.stringify({ mode: viewFilter.mode, entity_type: entityType, query: nextQuery });
    lastPersistedSearchFilter.current = JSON.stringify({ query: nextQuery.trim(), entity_type: entityType });
    hasLoadedSearchFilter.current = true;
    if (lastAppliedViewFilter.current === signature) return;
    lastAppliedViewFilter.current = signature;
    setQuery(nextQuery);
    if (entityType !== 'all') {
      setView('records');
      setRecordEntityFilter(entityFilterForEntity(entityType));
    }
  }, [data.view_state]);

  useEffect(() => {
    if (!hasLoadedSearchFilter.current) return;
    const entityType = view === 'records' ? recordEntityFilter : 'all';
    const nextQuery = query.trim();
    const signature = JSON.stringify({ query: nextQuery, entity_type: entityType });
    if (signature === lastPersistedSearchFilter.current) return;
    const timeout = window.setTimeout(() => {
      callBackend({ action: 'crm.set_view_filter', query: nextQuery, entity_type: entityType })
        .then(() => {
          lastPersistedSearchFilter.current = signature;
          setError('');
        })
        .catch((saveError: Error) => setError(saveError.message));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query, recordEntityFilter, view]);

  const viewModel = useMemo(() => buildCrmViewModel(data), [data]);

  useEffect(() => {
    setBulkSelection(new Set());
  }, [view]);

  return {
    actionDialog,
    bulkSelection,
    composer,
    data,
    error,
    filters,
    importPreview,
    isCreateChooserOpen,
    isLoading: isLoading || recordsLoading,
    isSaving,
    pipelineBoard,
    recordEntityFilter,
    recordsCursor,
    recordsCursorHistory,
    recordsData,
    recordsPageSize,
    reports,
    selected,
    setActionDialog,
    setBulkSelection,
    setComposer,
    setError,
    setFilters,
    setImportPreview,
    setIsCreateChooserOpen,
    setIsSaving,
    setQuery,
    setRecordEntityFilter,
    setRecordsCursor,
    setRecordsCursorHistory,
    setRecordsPageSize,
    setRecordsSort,
    setSelected,
    setView,
    view,
    viewModel,
    query,
    refresh,
    refreshPipelineBoard,
    refreshRecords
  };
}
