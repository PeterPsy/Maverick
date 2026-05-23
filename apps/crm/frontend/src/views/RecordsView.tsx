import { RecordsTablePayload, RecordsTableRow } from '../api';
import { RecordEntityFilter } from '../domain/types';
import { entityLabel, money, recordEntityFilters } from '../domain/routing';

export function RecordsView({
  data,
  entityFilter,
  hasPrevious,
  isLoading,
  onEntityFilterChange,
  onNextPage,
  onPreviousPage,
  onSelect,
  onSort,
  bulkSelection,
  setBulkSelection
}: {
  data: RecordsTablePayload | null;
  entityFilter: RecordEntityFilter;
  hasPrevious: boolean;
  isLoading: boolean;
  onEntityFilterChange: (value: RecordEntityFilter) => void;
  onNextPage: () => void;
  onPreviousPage: () => void;
  onSelect: (value: RecordsTableRow) => void;
  onSort: (field: string) => void;
  bulkSelection: Set<string>;
  setBulkSelection: (value: Set<string>) => void;
}) {
  const rows = data?.records || [];
  function toggle(row: RecordsTableRow) {
    const key = `${row.entity_type}:${row.id}`;
    const next = new Set(bulkSelection);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    setBulkSelection(next);
  }
  return (
    <section className="crm-panel records-view">
      <div className="records-header">
        <div>
          <small>Records</small>
          <h2>CRM records</h2>
        </div>
        <div className="entity-segment" role="tablist" aria-label="Record type">
          {recordEntityFilters.map((entity) => (
            <button key={entity} type="button" className={entityFilter === entity ? 'active' : ''} onClick={() => onEntityFilterChange(entity)}>
              {entity === 'all' ? 'All' : entityLabel(entity)}
            </button>
          ))}
        </div>
      </div>
      {isLoading ? <p className="muted">Loading CRM records...</p> : null}
      {!isLoading && rows.length === 0 ? <p className="muted">No records match this view.</p> : null}
      {rows.length ? (
        <div className="records-table-wrap">
          <table className="records-table">
            <thead>
              <tr>
                <th aria-label="Bulk select" />
                {(data?.columns || []).map((column) => (
                  <th key={column.key}>
                    <button type="button" onClick={() => onSort(sortFieldForColumn(column.key))}>{column.label}</button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.entity_type}:${row.id}`} onClick={() => onSelect(row)}>
                  <td onClick={(event) => event.stopPropagation()}>
                    <input type="checkbox" checked={bulkSelection.has(`${row.entity_type}:${row.id}`)} onChange={() => toggle(row)} aria-label={`Select ${row.title}`} />
                  </td>
                  {(data?.columns || []).map((column) => (
                    <td key={`${row.id}:${column.key}`}>{recordTableValue(row, column.key)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <footer className="records-pagination">
        <span>{Object.entries(data?.counts || {}).map(([entity, count]) => `${entity}: ${count}`).join(' · ')}</span>
        <div>
          <button type="button" onClick={onPreviousPage} disabled={!hasPrevious}>Previous</button>
          <button type="button" onClick={onNextPage} disabled={!data?.has_more}>Next</button>
        </div>
      </footer>
    </section>
  );
}

function sortFieldForColumn(columnKey: string) {
  const mapping: Record<string, string> = {
    last_touch: 'last_activity_at',
    last_activity: 'last_activity_at',
    status_stage: 'status',
    account_company: 'name',
    updated: 'updated_at',
    age: 'deal_age_days'
  };
  return mapping[columnKey] || columnKey;
}

function recordTableValue(row: RecordsTableRow, columnKey: string) {
  const record = row.record;
  const computed = row.computed || {};
  if (columnKey === 'type') return entityLabel(row.entity_type);
  if (columnKey === 'name') return row.title;
  if (columnKey === 'account_company') return String(record.account_id || record.company || record.domain || '');
  if (columnKey === 'account') return String(record.account_id || '');
  if (columnKey === 'contact') return String(record.contact_id || '');
  if (columnKey === 'owner') return String(record.owner_id || '');
  if (columnKey === 'status_stage') return String(record.status || record.stage || '');
  if (columnKey === 'value') return money(record);
  if (columnKey === 'weighted_value') return typeof computed.weighted_value === 'number' ? money({ value: computed.weighted_value, currency: record.currency }) : '';
  if (columnKey === 'next_action' || columnKey === 'next_step') return String(computed.next_action || '');
  if (columnKey === 'last_touch' || columnKey === 'last_activity') return String(computed.last_activity_at || '').slice(0, 10);
  if (columnKey === 'updated') return String(record.updated_at || '').slice(0, 10);
  if (columnKey === 'tags') return Array.isArray(record.tags) ? record.tags.map((tag) => typeof tag === 'object' && tag ? String((tag as { name?: unknown }).name || '') : '').filter(Boolean).join(', ') : '';
  if (columnKey in computed) return String(computed[columnKey] ?? '');
  return String(record[columnKey] ?? '');
}
