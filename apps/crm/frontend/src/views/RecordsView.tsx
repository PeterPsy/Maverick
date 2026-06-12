import { RecordsTablePayload, RecordsTableRow } from '../api';
import { RecordsTableWithModal } from '../components/ui/records-table-with-modal';
import { RecordEntityFilter } from '../domain/types';
import { entityLabel, money } from '../domain/routing';

export function RecordsView({
  data,
  entityFilter,
  hasPrevious,
  isLoading,
  currentPage,
  pageSize,
  onEntityFilterChange,
  onPageChange,
  onPageSizeChange,
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
  currentPage: number;
  pageSize: number;
  onEntityFilterChange: (value: RecordEntityFilter) => void;
  onPageChange: (value: number) => void;
  onPageSizeChange: (value: number) => void;
  onNextPage: () => void;
  onPreviousPage: () => void;
  onSelect: (value: RecordsTableRow) => void;
  onSort: (field: string) => void;
  bulkSelection: Set<string>;
  setBulkSelection: (value: Set<string>) => void;
}) {
  const rows = data?.records || [];
  return (
    <section className="crm-panel records-view">
      {isLoading ? <p className="muted">Loading CRM records...</p> : null}
      {!isLoading && rows.length === 0 ? <p className="muted">No records match this view.</p> : null}
      <RecordsTableWithModal
        title="CRM records"
        data={data}
        entityFilter={entityFilter}
        hasPrevious={hasPrevious}
        currentPage={currentPage}
        pageSize={pageSize}
        onEntityFilterChange={onEntityFilterChange}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
        onNextPage={onNextPage}
        onPreviousPage={onPreviousPage}
        onSelect={onSelect}
        onSort={onSort}
        bulkSelection={bulkSelection}
        setBulkSelection={setBulkSelection}
        renderValue={recordTableValue}
        sortFieldForColumn={sortFieldForColumn}
      />
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
  const display = row.display || {};
  if (columnKey.startsWith('custom:')) return customFieldValue(row, columnKey);
  if (columnKey === 'type') return entityLabel(row.entity_type);
  if (columnKey === 'name') return row.title;
  if (columnKey === 'account_company') return String(display.account || record.company || record.domain || '');
  if (columnKey === 'account') return String(display.account || '');
  if (columnKey === 'contact') return String(display.contact || '');
  if (columnKey === 'account_id') return String(display.account || '');
  if (columnKey === 'contact_id') return String(display.contact || '');
  if (columnKey === 'owner') return String(record.owner_id || '');
  if (columnKey === 'status_stage') return String(record.status || record.stage || '');
  if (columnKey === 'value') return money(record);
  if (columnKey === 'connections') return connectionValue(row);
  if (columnKey === 'weighted_value') return typeof computed.weighted_value === 'number' ? money({ value: computed.weighted_value, currency: record.currency }) : '';
  if (columnKey === 'next_action' || columnKey === 'next_step') return String(computed.next_action || '');
  if (columnKey === 'last_touch' || columnKey === 'last_activity') return String(computed.last_activity_at || '').slice(0, 10);
  if (columnKey === 'updated') return String(record.updated_at || '').slice(0, 10);
  if (columnKey === 'tags') return Array.isArray(record.tags) ? record.tags.map((tag) => typeof tag === 'object' && tag ? String((tag as { name?: unknown }).name || '') : '').filter(Boolean).join(', ') : '';
  if (columnKey in computed) return String(computed[columnKey] ?? '');
  return String(record[columnKey] ?? '');
}

function connectionValue(row: RecordsTableRow) {
  const summary = row.computed?.connection_summary;
  if (!summary || typeof summary !== 'object' || Array.isArray(summary)) return '';
  const badges = (summary as { badges?: Array<{ label?: unknown }> }).badges || [];
  return badges.map((badge) => String(badge.label || '')).filter(Boolean).join(', ');
}

function customFieldValue(row: RecordsTableRow, columnKey: string) {
  const [, maybeEntity, maybeField] = columnKey.split(':');
  const fieldKey = maybeField ? maybeField : maybeEntity;
  if (maybeField && maybeEntity !== row.entity_type) return '';
  const customFields = row.record.custom_fields && typeof row.record.custom_fields === 'object' ? row.record.custom_fields as Record<string, unknown> : {};
  const value = customFields[fieldKey];
  if (Array.isArray(value)) return value.map((item) => String(item)).join(', ');
  if (value && typeof value === 'object') return JSON.stringify(value);
  return String(value ?? '');
}
