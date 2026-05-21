import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { Building2, CheckSquare, Contact, Handshake, Pencil, StickyNote, X } from 'lucide-react';
import { BootstrapPayload, CrmRecord, CrmViewRef, callBackend } from './api';

type ViewId = 'dashboard' | 'accounts' | 'contacts' | 'deals' | 'activities' | 'tasks' | 'notes' | 'import';
type PendingSelection = { entity: string; id: string } | null;
type ImportPreview = { row_count?: number; counts?: Record<string, number>; warnings?: string[] };
type EntityRecord = { entity: string; record: CrmRecord };
type CreatableEntity = 'account' | 'contact' | 'deal' | 'task' | 'note';
type ComposerState =
  | { mode: 'create'; entity: CreatableEntity }
  | { mode: 'edit'; entity: CreatableEntity; record: CrmRecord }
  | null;

const viewIds: ViewId[] = ['dashboard', 'accounts', 'contacts', 'deals', 'activities', 'tasks', 'notes', 'import'];
const creatableEntities: CreatableEntity[] = ['account', 'contact', 'deal', 'task', 'note'];
const createActions: Record<CreatableEntity, string> = {
  account: 'crm.create_account',
  contact: 'crm.create_contact',
  deal: 'crm.create_deal',
  task: 'crm.create_task',
  note: 'crm.create_note'
};
const updateActions: Record<CreatableEntity, string> = {
  account: 'crm.update_account',
  contact: 'crm.update_contact',
  deal: 'crm.update_deal',
  task: 'crm.update_task',
  note: 'crm.update_note'
};
const createTargets = [
  { label: 'Account', entity: 'account', icon: Building2 },
  { label: 'Contact', entity: 'contact', icon: Contact },
  { label: 'Deal', entity: 'deal', icon: Handshake },
  { label: 'Task', entity: 'task', icon: CheckSquare },
  { label: 'Note', entity: 'note', icon: StickyNote }
] satisfies Array<{ label: string; entity: CreatableEntity; icon: typeof Building2 }>;

const emptyPayload: BootstrapPayload = {
  ok: true,
  accounts: [],
  contacts: [],
  deals: [],
  tasks: [],
  notes: [],
  activities: [],
  pipeline_stages: [],
  counts: {},
  view_state: { view_filter: { mode: 'search', query: '', entity_type: 'all', refs: [], title: '' } }
};

function titleFor(record: CrmRecord) {
  return record.name || record.display_name || record.subject || record.title || String(record.body || '').slice(0, 48) || record.id;
}

function viewFromAppPage(appPage: string): { view: ViewId; selection: PendingSelection } {
  const [segment, recordId] = appPage.split('/').filter(Boolean);
  const route = segment || 'dashboard';
  const view = viewIds.includes(route as ViewId) ? (route as ViewId) : 'dashboard';
  const entityByView: Partial<Record<ViewId, string>> = {
    accounts: 'account',
    contacts: 'contact',
    deals: 'deal',
    activities: 'activity',
    tasks: 'task',
    notes: 'note'
  };
  return { view, selection: recordId && entityByView[view] ? { entity: entityByView[view], id: recordId } : null };
}

function money(record: CrmRecord) {
  const value = Number(record.value || 0);
  if (!value) return '';
  return `${record.currency || 'EUR'} ${value.toLocaleString()}`;
}

function recordKey(entity: string, record: CrmRecord) {
  return `${entity}:${record.id}`;
}

function fieldLabel(key: string) {
  return key.replace(/_/g, ' ');
}

function refKey(ref: CrmViewRef) {
  const entityType = String(ref.entity_type || '');
  const rawId = String(ref.entity_id || ref.id || '');
  const id = rawId.includes(':') ? rawId.split(':').slice(1).join(':') : rawId;
  return entityType && id ? `${entityType}:${id}` : '';
}

function viewForEntity(entityType: string): ViewId {
  const mapping: Record<string, ViewId> = {
    account: 'accounts',
    contact: 'contacts',
    deal: 'deals',
    activity: 'activities',
    task: 'tasks',
    note: 'notes'
  };
  return mapping[entityType] || 'dashboard';
}

function isCreatableEntity(value: unknown): value is CreatableEntity {
  return typeof value === 'string' && creatableEntities.includes(value as CreatableEntity);
}

function entityLabel(entity: string) {
  const labels: Record<string, string> = {
    account: 'Account',
    contact: 'Contact',
    deal: 'Deal',
    activity: 'Activity',
    task: 'Task',
    note: 'Note'
  };
  return labels[entity] || entity;
}

export function App() {
  const [view, setView] = useState<ViewId>('dashboard');
  const [data, setData] = useState<BootstrapPayload>(emptyPayload);
  const [selected, setSelected] = useState<{ entity: string; record: CrmRecord } | null>(null);
  const [composer, setComposer] = useState<ComposerState>(null);
  const [isCreateChooserOpen, setIsCreateChooserOpen] = useState(false);
  const [pendingSelection, setPendingSelection] = useState<PendingSelection>(null);
  const [query, setQuery] = useState('');
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
          setComposer({ mode: 'create', entity: params.entity_type });
          return;
        }
        const navigation = viewFromAppPage(appPage);
        setView(navigation.view);
        setPendingSelection(navigation.selection);
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  useEffect(() => {
    if (!pendingSelection) return;
    const recordsByEntity: Record<string, CrmRecord[]> = {
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
      setView(viewForEntity(entityType));
    }
  }, [data.view_state]);

  const viewModel = useMemo(() => {
    const viewFilter = data.view_state?.view_filter;
    const refs = new Set((viewFilter?.refs || []).map(refKey).filter(Boolean));
    const isCustom = viewFilter?.mode === 'custom' && refs.size > 0;
    const searchEntityType = viewFilter?.mode === 'search' && viewFilter.entity_type ? viewFilter.entity_type : 'all';
    const filterRecords = (entity: string, records: CrmRecord[]) => {
      const scopedRecords = searchEntityType !== 'all' && searchEntityType !== entity ? [] : records;
      return isCustom ? scopedRecords.filter((record) => refs.has(recordKey(entity, record))) : scopedRecords;
    };
    const accounts = filterRecords('account', data.accounts);
    const contacts = filterRecords('contact', data.contacts);
    const deals = filterRecords('deal', data.deals);
    const activities = filterRecords('activity', data.activities);
    const tasks = filterRecords('task', data.tasks);
    const notes = filterRecords('note', data.notes);
    const all: EntityRecord[] = [
      ...accounts.map((record) => ({ entity: 'account', record })),
      ...contacts.map((record) => ({ entity: 'contact', record })),
      ...deals.map((record) => ({ entity: 'deal', record })),
      ...activities.map((record) => ({ entity: 'activity', record })),
      ...tasks.map((record) => ({ entity: 'task', record })),
      ...notes.map((record) => ({ entity: 'note', record }))
    ];
    return {
      accounts,
      contacts,
      deals,
      activities,
      tasks,
      notes,
      all,
      isCustom,
      title: viewFilter?.title || 'Custom view'
    };
  }, [data]);

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return viewModel.all;
    return viewModel.all.filter(({ record }) => JSON.stringify(record).toLowerCase().includes(term));
  }, [query, viewModel]);

  async function saveComposer(state: Exclude<ComposerState, null>, values: Record<string, unknown>) {
    setIsSaving(true);
    setError('');
    try {
      const action = state.mode === 'create' ? createActions[state.entity] : updateActions[state.entity];
      const body = state.mode === 'edit' ? { ...values, id: state.record.id } : values;
      await callBackend({ action, ...body });
      setView(viewForEntity(state.entity));
      setComposer(null);
      await refresh();
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
        csv: form.get('csv')
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

        {view === 'dashboard' ? <Dashboard data={{ ...data, accounts: viewModel.accounts, contacts: viewModel.contacts, deals: viewModel.deals, activities: viewModel.activities, tasks: viewModel.tasks, notes: viewModel.notes }} filtered={filtered} select={setSelected} isLoading={isLoading} /> : null}
        {view === 'accounts' ? <RecordTable entity="account" records={viewModel.accounts} select={setSelected} /> : null}
        {view === 'contacts' ? <RecordTable entity="contact" records={viewModel.contacts} select={setSelected} /> : null}
        {view === 'deals' ? <Pipeline data={{ ...data, deals: viewModel.deals }} select={setSelected} /> : null}
        {view === 'activities' ? <RecordTable entity="activity" label="Activities" records={viewModel.activities} select={setSelected} /> : null}
        {view === 'tasks' ? <RecordTable entity="task" records={viewModel.tasks} select={setSelected} /> : null}
        {view === 'notes' ? <RecordTable entity="note" records={viewModel.notes} select={setSelected} /> : null}
        {view === 'import' ? <ImportPanel onSubmit={handleImport} isSaving={isSaving} preview={importPreview} /> : null}
      </section>

      {selected ? (
        <RecordDetailModal
          selected={selected}
          onClose={() => setSelected(null)}
          onEdit={(entity, record) => {
            if (!isCreatableEntity(entity)) return;
            setSelected(null);
            setComposer({ mode: 'edit', entity, record });
          }}
        />
      ) : null}
      {isCreateChooserOpen ? (
        <CreateChooserModal
          onClose={() => setIsCreateChooserOpen(false)}
          onChoose={(entity) => {
            setIsCreateChooserOpen(false);
            setView(viewForEntity(entity));
            setComposer({ mode: 'create', entity });
          }}
        />
      ) : null}
      {composer ? <RecordComposerModal state={composer} data={data} isSaving={isSaving} onClose={() => setComposer(null)} onSubmit={(values) => saveComposer(composer, values)} /> : null}
    </main>
  );
}

function Dashboard({ data, filtered, select, isLoading }: { data: BootstrapPayload; filtered: Array<{ entity: string; record: CrmRecord }>; select: (value: { entity: string; record: CrmRecord }) => void; isLoading: boolean }) {
  const metrics = [
    { label: 'Accounts', value: data.accounts.length, icon: Building2 },
    { label: 'Contacts', value: data.contacts.length, icon: Contact },
    { label: 'Open deals', value: data.deals.filter((deal) => !['Won', 'Lost'].includes(String(deal.stage))).length, icon: Handshake },
    { label: 'Activities', value: data.activities.length, icon: CheckSquare },
    { label: 'Tasks', value: data.tasks.length, icon: CheckSquare },
    { label: 'Notes', value: data.notes.length, icon: StickyNote }
  ];
  return (
    <div className="crm-dashboard">
      <section className="crm-metrics">
        {metrics.map((metric) => {
          const Icon = metric.icon;
          return (
            <div className="metric" key={metric.label}>
              <Icon size={16} aria-hidden="true" />
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
            </div>
          );
        })}
      </section>
      <section className="crm-panel">
        <h2>Recent records</h2>
        {isLoading ? <p className="muted">Loading CRM data...</p> : null}
        {!isLoading && filtered.length === 0 ? <p className="muted">No CRM records yet.</p> : null}
        <div className="record-list">
          {filtered.slice(0, 12).map((item) => (
            <button key={`${item.entity}:${item.record.id}`} onClick={() => select(item)}>
              <span>{titleFor(item.record)}</span>
              <small>{item.entity}</small>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function RecordTable({ entity, label, records, select }: { entity: string; label?: string; records: CrmRecord[]; select: (value: { entity: string; record: CrmRecord }) => void }) {
  const tableTitle = label || `${entity[0].toUpperCase() + entity.slice(1)}s`;
  return (
    <section className="crm-panel">
      <h2>{tableTitle}</h2>
      {records.length === 0 ? <p className="muted">No {entity} records.</p> : null}
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Status</th>
            <th>Value</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={record.id} onClick={() => select({ entity, record })}>
              <td>{titleFor(record)}</td>
              <td>{String(record.status || record.stage || '')}</td>
              <td>{money(record)}</td>
              <td>{String(record.updated_at || '').slice(0, 10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Pipeline({ data, select }: { data: BootstrapPayload; select: (value: { entity: string; record: CrmRecord }) => void }) {
  return (
    <section className="pipeline-board">
      {data.pipeline_stages.map((stage) => (
        <div className="pipeline-column" key={stage.id}>
          <h2>{stage.name}</h2>
          {data.deals
            .filter((deal) => deal.stage_id === stage.id || deal.stage === stage.name)
            .map((deal) => (
              <button className="deal-card" key={deal.id} onClick={() => select({ entity: 'deal', record: deal })}>
                <strong>{titleFor(deal)}</strong>
                <span>{money(deal) || 'No value'}</span>
              </button>
            ))}
        </div>
      ))}
    </section>
  );
}

function ImportPanel({ onSubmit, isSaving, preview }: { onSubmit: (event: FormEvent<HTMLFormElement>) => void; isSaving: boolean; preview: ImportPreview | null }) {
  return (
    <section className="crm-panel import-panel">
      <h2>Import</h2>
      <form onSubmit={onSubmit}>
        <label>
          Entity
          <select name="entity_type" defaultValue="contact">
            <option value="account">Accounts</option>
            <option value="contact">Contacts</option>
            <option value="deal">Deals</option>
            <option value="activity">Activities</option>
            <option value="task">Tasks</option>
            <option value="note">Notes</option>
          </select>
        </label>
        <label>
          CSV
          <textarea name="csv" rows={10} placeholder="display_name,email&#10;Ada Lovelace,ada@example.com" />
        </label>
        <div className="import-actions">
          <button type="submit" name="preview" disabled={isSaving}>Preview</button>
          <button type="submit" name="commit" disabled={isSaving}>Commit import</button>
        </div>
      </form>
      {preview ? (
        <div className="import-preview">
          <strong>Preview</strong>
          <span>{preview.row_count ?? 0} rows</span>
          {preview.counts ? <pre>{JSON.stringify(preview.counts, null, 2)}</pre> : null}
        </div>
      ) : null}
    </section>
  );
}

function textValue(record: Partial<CrmRecord>, key: string, fallback = '') {
  const value = record[key];
  return value === null || value === undefined ? fallback : String(value);
}

function numericValue(record: Partial<CrmRecord>, key: string, fallback = '') {
  const value = record[key];
  return typeof value === 'number' || typeof value === 'string' ? String(value) : fallback;
}

function SelectField({ label, name, defaultValue, children }: { label: string; name: string; defaultValue?: string; children: ReactNode }) {
  return (
    <label>
      {label}
      <select name={name} defaultValue={defaultValue || ''}>
        {children}
      </select>
    </label>
  );
}

function RelatedRecordOptions({ records }: { records: CrmRecord[] }) {
  return (
    <>
      <option value="">None</option>
      {records.map((record) => (
        <option key={record.id} value={record.id}>
          {titleFor(record)}
        </option>
      ))}
    </>
  );
}

function appendText(form: FormData, payload: Record<string, unknown>, key: string) {
  const value = form.get(key);
  payload[key] = typeof value === 'string' ? value.trim() : '';
}

function appendNumber(form: FormData, payload: Record<string, unknown>, key: string) {
  const value = form.get(key);
  const text = typeof value === 'string' ? value.trim() : '';
  payload[key] = text ? Number(text) : 0;
}

function CreateChooserModal({ onClose, onChoose }: { onClose: () => void; onChoose: (entity: CreatableEntity) => void }) {
  return (
    <div className="crm-detail-overlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="crm-detail-dialog crm-create-chooser-dialog" role="dialog" aria-modal="true" aria-labelledby="crm-create-chooser-title">
        <header className="detail-header">
          <div>
            <small>create</small>
            <h2 id="crm-create-chooser-title">Add CRM record</h2>
          </div>
          <button className="detail-close" type="button" onClick={onClose} aria-label="Close create menu">
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="create-chooser-list">
          {createTargets.map((target) => {
            const Icon = target.icon;
            return (
              <button key={target.entity} type="button" onClick={() => onChoose(target.entity)}>
                <Icon size={18} aria-hidden="true" />
                <span>{target.label}</span>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function RecordComposerModal({
  state,
  data,
  isSaving,
  onClose,
  onSubmit
}: {
  state: Exclude<ComposerState, null>;
  data: BootstrapPayload;
  isSaving: boolean;
  onClose: () => void;
  onSubmit: (values: Record<string, unknown>) => void;
}) {
  const record = state.mode === 'edit' ? state.record : {};
  const title = `${state.mode === 'create' ? 'Add' : 'Edit'} ${entityLabel(state.entity)}`;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const values: Record<string, unknown> = {};
    if (state.entity === 'account') {
      ['name', 'domain', 'industry', 'status', 'owner_id', 'summary'].forEach((key) => appendText(form, values, key));
    } else if (state.entity === 'contact') {
      ['display_name', 'first_name', 'last_name', 'email', 'phone', 'role', 'account_id', 'owner_id', 'summary'].forEach((key) => appendText(form, values, key));
    } else if (state.entity === 'deal') {
      ['name', 'account_id', 'contact_id', 'stage_id', 'currency', 'close_date', 'owner_id', 'summary'].forEach((key) => appendText(form, values, key));
      appendNumber(form, values, 'value');
      appendNumber(form, values, 'probability');
    } else if (state.entity === 'task') {
      ['title', 'status', 'priority', 'due_at', 'account_id', 'contact_id', 'deal_id', 'owner_id', 'body'].forEach((key) => appendText(form, values, key));
    } else {
      ['body', 'account_id', 'contact_id', 'deal_id', 'owner_id'].forEach((key) => appendText(form, values, key));
    }
    onSubmit(values);
  }

  return (
    <div className="crm-detail-overlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="crm-detail-dialog crm-composer-dialog" role="dialog" aria-modal="true" aria-labelledby="crm-composer-title">
        <header className="detail-header">
          <div>
            <small>{state.mode}</small>
            <h2 id="crm-composer-title">{title}</h2>
          </div>
          <button className="detail-close" type="button" onClick={onClose} aria-label="Close composer">
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <form className="composer-form" onSubmit={handleSubmit}>
          {state.entity === 'account' ? (
            <div className="composer-grid">
              <label>
                Name
                <input name="name" required defaultValue={textValue(record, 'name')} />
              </label>
              <label>
                Domain
                <input name="domain" defaultValue={textValue(record, 'domain')} />
              </label>
              <label>
                Industry
                <input name="industry" defaultValue={textValue(record, 'industry')} />
              </label>
              <SelectField label="Status" name="status" defaultValue={textValue(record, 'status', 'prospect')}>
                <option value="prospect">Prospect</option>
                <option value="customer">Customer</option>
                <option value="partner">Partner</option>
                <option value="inactive">Inactive</option>
              </SelectField>
              <label>
                Owner
                <input name="owner_id" defaultValue={textValue(record, 'owner_id')} />
              </label>
              <label className="span-2">
                Summary
                <textarea name="summary" rows={4} defaultValue={textValue(record, 'summary')} />
              </label>
            </div>
          ) : null}

          {state.entity === 'contact' ? (
            <div className="composer-grid">
              <label>
                Display name
                <input name="display_name" required defaultValue={textValue(record, 'display_name')} />
              </label>
              <label>
                Email
                <input name="email" type="email" defaultValue={textValue(record, 'email')} />
              </label>
              <label>
                First name
                <input name="first_name" defaultValue={textValue(record, 'first_name')} />
              </label>
              <label>
                Last name
                <input name="last_name" defaultValue={textValue(record, 'last_name')} />
              </label>
              <SelectField label="Account" name="account_id" defaultValue={textValue(record, 'account_id')}>
                <RelatedRecordOptions records={data.accounts} />
              </SelectField>
              <label>
                Phone
                <input name="phone" defaultValue={textValue(record, 'phone')} />
              </label>
              <label>
                Role
                <input name="role" defaultValue={textValue(record, 'role')} />
              </label>
              <label>
                Owner
                <input name="owner_id" defaultValue={textValue(record, 'owner_id')} />
              </label>
              <label className="span-2">
                Summary
                <textarea name="summary" rows={4} defaultValue={textValue(record, 'summary')} />
              </label>
            </div>
          ) : null}

          {state.entity === 'deal' ? (
            <div className="composer-grid">
              <label>
                Name
                <input name="name" required defaultValue={textValue(record, 'name')} />
              </label>
              <SelectField label="Stage" name="stage_id" defaultValue={textValue(record, 'stage_id', 'lead')}>
                {data.pipeline_stages.map((stage) => (
                  <option key={stage.id} value={stage.id}>
                    {stage.name}
                  </option>
                ))}
              </SelectField>
              <SelectField label="Account" name="account_id" defaultValue={textValue(record, 'account_id')}>
                <RelatedRecordOptions records={data.accounts} />
              </SelectField>
              <SelectField label="Contact" name="contact_id" defaultValue={textValue(record, 'contact_id')}>
                <RelatedRecordOptions records={data.contacts} />
              </SelectField>
              <label>
                Value
                <input name="value" type="number" min="0" step="0.01" defaultValue={numericValue(record, 'value', '0')} />
              </label>
              <label>
                Currency
                <input name="currency" defaultValue={textValue(record, 'currency', 'EUR')} />
              </label>
              <label>
                Probability
                <input name="probability" type="number" min="0" max="1" step="0.01" defaultValue={numericValue(record, 'probability', '0')} />
              </label>
              <label>
                Close date
                <input name="close_date" type="date" defaultValue={textValue(record, 'close_date')} />
              </label>
              <label>
                Owner
                <input name="owner_id" defaultValue={textValue(record, 'owner_id')} />
              </label>
              <label className="span-2">
                Summary
                <textarea name="summary" rows={4} defaultValue={textValue(record, 'summary')} />
              </label>
            </div>
          ) : null}

          {state.entity === 'task' ? (
            <div className="composer-grid">
              <label>
                Title
                <input name="title" required defaultValue={textValue(record, 'title')} />
              </label>
              <SelectField label="Status" name="status" defaultValue={textValue(record, 'status', 'open')}>
                <option value="open">Open</option>
                <option value="done">Done</option>
                <option value="blocked">Blocked</option>
              </SelectField>
              <SelectField label="Priority" name="priority" defaultValue={textValue(record, 'priority', 'normal')}>
                <option value="low">Low</option>
                <option value="normal">Normal</option>
                <option value="high">High</option>
              </SelectField>
              <label>
                Due date
                <input name="due_at" type="date" defaultValue={textValue(record, 'due_at')} />
              </label>
              <SelectField label="Account" name="account_id" defaultValue={textValue(record, 'account_id')}>
                <RelatedRecordOptions records={data.accounts} />
              </SelectField>
              <SelectField label="Contact" name="contact_id" defaultValue={textValue(record, 'contact_id')}>
                <RelatedRecordOptions records={data.contacts} />
              </SelectField>
              <SelectField label="Deal" name="deal_id" defaultValue={textValue(record, 'deal_id')}>
                <RelatedRecordOptions records={data.deals} />
              </SelectField>
              <label>
                Owner
                <input name="owner_id" defaultValue={textValue(record, 'owner_id')} />
              </label>
              <label className="span-2">
                Notes
                <textarea name="body" rows={4} defaultValue={textValue(record, 'body')} />
              </label>
            </div>
          ) : null}

          {state.entity === 'note' ? (
            <div className="composer-grid">
              <label className="span-2">
                Note
                <textarea name="body" required rows={7} defaultValue={textValue(record, 'body')} />
              </label>
              <SelectField label="Account" name="account_id" defaultValue={textValue(record, 'account_id')}>
                <RelatedRecordOptions records={data.accounts} />
              </SelectField>
              <SelectField label="Contact" name="contact_id" defaultValue={textValue(record, 'contact_id')}>
                <RelatedRecordOptions records={data.contacts} />
              </SelectField>
              <SelectField label="Deal" name="deal_id" defaultValue={textValue(record, 'deal_id')}>
                <RelatedRecordOptions records={data.deals} />
              </SelectField>
              <label>
                Owner
                <input name="owner_id" defaultValue={textValue(record, 'owner_id')} />
              </label>
            </div>
          ) : null}

          <div className="composer-actions">
            <button type="button" onClick={onClose}>Cancel</button>
            <button type="submit" disabled={isSaving}>{isSaving ? 'Saving...' : 'Save'}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

function RecordDetailModal({ selected, onClose, onEdit }: { selected: { entity: string; record: CrmRecord }; onClose: () => void; onEdit: (entity: string, record: CrmRecord) => void }) {
  return (
    <div className="crm-detail-overlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="crm-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="crm-detail-title">
        <header className="detail-header">
          <div>
            <small>{selected.entity}</small>
            <h2 id="crm-detail-title">{titleFor(selected.record)}</h2>
          </div>
          <div className="detail-actions">
            {isCreatableEntity(selected.entity) ? (
              <button className="detail-icon-button" type="button" onClick={() => onEdit(selected.entity, selected.record)} aria-label="Edit record">
                <Pencil size={17} aria-hidden="true" />
              </button>
            ) : null}
            <button className="detail-close" type="button" onClick={onClose} aria-label="Close record details">
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </header>
        <dl className="detail-fields">
          {Object.entries(selected.record)
            .filter(([, value]) => value !== '' && value !== null && value !== undefined && typeof value !== 'object')
            .slice(0, 16)
            .map(([key, value]) => (
              <div key={key}>
                <dt>{fieldLabel(key)}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))}
        </dl>
      </section>
    </div>
  );
}
