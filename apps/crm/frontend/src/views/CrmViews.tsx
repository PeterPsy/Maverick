import { Contact, Save, SlidersHorizontal, Tag } from 'lucide-react';
import { BootstrapPayload, CrmRecord, DuplicateGroup, IntelligentNextAction, SavedView } from '../api';
import { SalesReportsPayload } from '../domain/types';
import { money, recordKey, titleFor } from '../domain/routing';

export function WorkspaceToolbar({
  filters,
  savedViews,
  selectedCount,
  onApplySavedView,
  onBulkArchive,
  onBulkTag,
  onFilterChange,
  onSaveView
}: {
  filters: Record<string, string>;
  savedViews: SavedView[];
  selectedCount: number;
  onApplySavedView: (savedView: SavedView) => void;
  onBulkArchive: () => void;
  onBulkTag: () => void;
  onFilterChange: (filters: Record<string, string>) => void;
  onSaveView: () => void;
}) {
  return (
    <section className="crm-filter-strip" aria-label="CRM filters and saved views">
      <label>
        <SlidersHorizontal size={15} aria-hidden="true" />
        <input value={filters.status || ''} onChange={(event) => onFilterChange({ ...filters, status: event.target.value })} placeholder="Status or stage" />
      </label>
      <label>
        <Contact size={15} aria-hidden="true" />
        <input value={filters.owner_id || ''} onChange={(event) => onFilterChange({ ...filters, owner_id: event.target.value })} placeholder="Owner" />
      </label>
      <label>
        <Tag size={15} aria-hidden="true" />
        <input value={filters.tag || ''} onChange={(event) => onFilterChange({ ...filters, tag: event.target.value })} placeholder="Tag" />
      </label>
      <button type="button" onClick={onSaveView}>
        <Save size={15} aria-hidden="true" />
        <span>Save view</span>
      </button>
      {savedViews.length ? (
        <select defaultValue="" onChange={(event) => {
          const savedView = savedViews.find((item) => item.id === event.target.value);
          if (savedView) onApplySavedView(savedView);
        }}>
          <option value="">Saved views</option>
          {savedViews.map((savedView) => (
            <option key={savedView.id} value={savedView.id}>{savedView.title}</option>
          ))}
        </select>
      ) : null}
      {selectedCount ? (
        <div className="bulk-actions">
          <span>{selectedCount} selected</span>
          <button type="button" onClick={onBulkTag}>Tag</button>
          <button type="button" onClick={onBulkArchive}>Archive</button>
        </div>
      ) : null}
    </section>
  );
}

export function OperationsView({ data, select }: { data: BootstrapPayload; select: (value: { entity: string; record: CrmRecord }) => void }) {
  const openTasks = data.tasks.filter((task) => task.status === 'open');
  return (
    <div className="operations-view">
      <RecordTable entity="task" label="My tasks" records={openTasks} select={select} bulkSelection={new Set()} setBulkSelection={() => undefined} />
      <NextActionPanel actions={data.next_action_suggestions || []} select={select} />
      <DuplicatePanel groups={data.duplicates?.groups || []} select={select} />
    </div>
  );
}

export function ReportsView({ reports, isLoading }: { reports: SalesReportsPayload | null; isLoading: boolean }) {
  const forecast = reports?.weighted_forecast || {};
  const conversion = reports?.lead_conversion || {};
  const kpis = [
    { label: 'Open pipeline', value: money({ value: forecast.total_value || 0, currency: 'EUR' }) || 'EUR 0' },
    { label: 'Weighted forecast', value: money({ value: forecast.total_weighted_value || 0, currency: 'EUR' }) || 'EUR 0' },
    { label: 'Conversion rate', value: `${Math.round(Number(conversion.conversion_rate || 0) * 100)}%` },
    { label: 'Overdue tasks', value: String(reports?.task_overdue?.total || 0) }
  ];
  return (
    <div className="reports-view">
      <section className="crm-metrics">
        {kpis.map((metric) => (
          <div className="metric" key={metric.label}>
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
          </div>
        ))}
      </section>
      {isLoading ? <p className="muted">Loading reports...</p> : null}
      <section className="crm-panel">
        <h2>Pipeline by stage</h2>
        <div className="report-list">
          {(reports?.pipeline_value_by_stage || []).map((item) => (
            <div key={item.stage_id || item.stage}>
              <strong>{item.stage || item.stage_id}</strong>
              <span>{item.count || 0} deals · {money({ value: item.total_value || 0, currency: item.currency || 'EUR' })}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="crm-panel">
        <h2>Deal aging</h2>
        <div className="report-list">
          {(reports?.deal_aging || []).slice(0, 8).map((item) => (
            <div key={item.id || item.name}>
              <strong>{item.name}</strong>
              <span>{item.stage} · {item.age_days || 0} days</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function NextActionPanel({ actions, select }: { actions: IntelligentNextAction[]; select: (value: { entity: string; record: CrmRecord }) => void }) {
  return (
    <section className="crm-panel">
      <h2>Next actions</h2>
      {actions.length === 0 ? <p className="muted">No suggested next actions.</p> : null}
      <div className="record-list">
        {actions.slice(0, 8).map((action) => (
          <button
            key={`${action.kind}:${action.entity_type}:${action.entity_id}:${action.title}`}
            type="button"
            onClick={() => {
              const record = action.record as CrmRecord | undefined;
              if (record) select({ entity: action.entity_type, record });
            }}
          >
            <span>{action.title}</span>
            <small>{action.score} · {action.reason}</small>
          </button>
        ))}
      </div>
    </section>
  );
}

function DuplicatePanel({ groups, select }: { groups: DuplicateGroup[]; select: (value: { entity: string; record: CrmRecord }) => void }) {
  return (
    <section className="crm-panel">
      <h2>Duplicates</h2>
      {groups.length === 0 ? <p className="muted">No duplicates detected.</p> : null}
      <div className="record-list">
        {groups.slice(0, 8).map((group) => (
          <button key={`${group.entity_type}:${group.field}:${group.value}`} type="button" onClick={() => select({ entity: group.entity_type, record: group.records[0] })}>
            <span>{group.field}: {group.value}</span>
            <small>{group.count} {group.entity_type}s</small>
          </button>
        ))}
      </div>
    </section>
  );
}

function RecordTable({
  entity,
  label,
  records,
  select,
  bulkSelection,
  setBulkSelection
}: {
  entity: string;
  label?: string;
  records: CrmRecord[];
  select: (value: { entity: string; record: CrmRecord }) => void;
  bulkSelection: Set<string>;
  setBulkSelection: (value: Set<string>) => void;
}) {
  const tableTitle = label || `${entity[0].toUpperCase() + entity.slice(1)}s`;
  function toggle(record: CrmRecord) {
    const key = recordKey(entity, record);
    const next = new Set(bulkSelection);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    setBulkSelection(next);
  }
  return (
    <section className="crm-panel">
      <h2>{tableTitle}</h2>
      {records.length === 0 ? <p className="muted">No {entity} records.</p> : null}
      <table>
        <thead>
          <tr>
            <th aria-label="Bulk select" />
            <th>Name</th>
            <th>Status</th>
            <th>Value</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={record.id} onClick={() => select({ entity, record })}>
              <td onClick={(event) => event.stopPropagation()}>
                <input type="checkbox" checked={bulkSelection.has(recordKey(entity, record))} onChange={() => toggle(record)} aria-label={`Select ${titleFor(record)}`} />
              </td>
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
