import { useMemo, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ArrowUpDown, ChevronDown, Download, Filter, User } from 'lucide-react';
import { RecordsTableColumn, RecordsTablePayload, RecordsTableRow } from '../../api';
import { ConnectionSummary, RecordEntityFilter } from '../../domain/types';
import { entityLabel, recordEntityFilters } from '../../domain/routing';
import SlidingPagination from './sliding-pagination';

type RecordsTableWithModalProps = {
  title?: string;
  data: RecordsTablePayload | null;
  entityFilter: RecordEntityFilter;
  hasPrevious: boolean;
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
  renderValue: (row: RecordsTableRow, columnKey: string) => string;
  sortFieldForColumn: (columnKey: string) => string;
};

const rowVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -6 }
};

const RECORDS_TABLE_SELECT_COLUMN_WIDTH = '3rem';
const RECORDS_TABLE_MIN_COLUMN_CH = 10;
const RECORDS_TABLE_MAX_COLUMN_CH = 76;
const RECORDS_TABLE_CELL_BUFFER_CH = 4;

export function RecordsTableWithModal({
  title = 'CRM records',
  data,
  entityFilter,
  hasPrevious,
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
  setBulkSelection,
  renderValue,
  sortFieldForColumn
}: RecordsTableWithModalProps) {
  const rows = data?.records || [];
  const columns = data?.columns || [];
  const [showFilterMenu, setShowFilterMenu] = useState(false);
  const [showSortMenu, setShowSortMenu] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const reduceMotion = useReducedMotion();
  const visibleKeys = useMemo(() => rows.map(rowKey), [rows]);
  const selectedVisibleCount = visibleKeys.filter((key) => bulkSelection.has(key)).length;
  const allVisibleSelected = visibleKeys.length > 0 && selectedVisibleCount === visibleKeys.length;
  const totalRecords = totalForEntity(data?.counts || {}, entityFilter);
  const totalPages = Math.max(1, Math.ceil(totalRecords / pageSize));
  const selectablePageCount = Math.max(currentPage, Math.min(totalPages, currentPage + (data?.has_more ? 1 : 0)));
  const visibleStart = totalRecords === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const visibleEnd = totalRecords === 0 ? 0 : Math.min(currentPage * pageSize, totalRecords);
  const columnWidths = useMemo(
    () => columns.map((column) => widthForColumn(column, rows, renderValue)),
    [columns, rows, renderValue]
  );
  const tableMinWidth = useMemo(
    () => {
      const columnWidthSum = columnWidths.length ? `${columnWidths.map((width) => width.preferredCh).join('ch + ')}ch` : '0ch';
      return `calc(${RECORDS_TABLE_SELECT_COLUMN_WIDTH} + ${columnWidthSum})`;
    },
    [columnWidths]
  );

  function toggle(row: RecordsTableRow) {
    const key = rowKey(row);
    const next = new Set(bulkSelection);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    setBulkSelection(next);
  }

  function toggleAllVisible() {
    const next = new Set(bulkSelection);
    if (allVisibleSelected) {
      visibleKeys.forEach((key) => next.delete(key));
    } else {
      visibleKeys.forEach((key) => next.add(key));
    }
    setBulkSelection(next);
  }

  function handleExport(format: 'csv' | 'json') {
    const filename = `crm-records-${new Date().toISOString().slice(0, 10)}.${format}`;
    const content = format === 'csv' ? csvForRows(rows, columns, renderValue) : JSON.stringify(rows, null, 2);
    const type = format === 'csv' ? 'text/csv;charset=utf-8;' : 'application/json;charset=utf-8;';
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([content], { type }));
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
    setShowExportMenu(false);
  }

  return (
    <div className="records-table-shell">
      <div className="records-command-bar">
        <div className="records-title-block">
          <small>Records</small>
          <h2>{title}</h2>
        </div>
        <div className="records-controls" aria-label="Records controls">
          <div className="records-menu">
            <button type="button" className={entityFilter !== 'all' ? 'active' : ''} onClick={() => setShowFilterMenu((open) => !open)}>
              <Filter aria-hidden="true" />
              <span>Filter</span>
              {entityFilter !== 'all' ? <strong>1</strong> : null}
            </button>
            {showFilterMenu ? (
              <RecordsMenu onClose={() => setShowFilterMenu(false)}>
                <button type="button" role="menuitem" onClick={() => { onEntityFilterChange('all'); setShowFilterMenu(false); }}>All records</button>
                {recordEntityFilters.filter((entity) => entity !== 'all').map((entity) => (
                  <button key={entity} type="button" role="menuitem" onClick={() => { onEntityFilterChange(entity); setShowFilterMenu(false); }}>
                    {entityLabel(entity)}
                  </button>
                ))}
              </RecordsMenu>
            ) : null}
          </div>
          <div className="records-menu">
            <button type="button" onClick={() => setShowSortMenu((open) => !open)}>
              <ArrowUpDown aria-hidden="true" />
              <span>Sort</span>
              <ChevronDown aria-hidden="true" />
            </button>
            {showSortMenu ? (
              <RecordsMenu onClose={() => setShowSortMenu(false)}>
                {columns.map((column) => (
                  <button key={column.key} type="button" role="menuitem" onClick={() => { onSort(sortFieldForColumn(column.key)); setShowSortMenu(false); }}>
                    {column.label}
                  </button>
                ))}
              </RecordsMenu>
            ) : null}
          </div>
          <div className="records-menu">
            <button type="button" onClick={() => setShowExportMenu((open) => !open)}>
              <Download aria-hidden="true" />
              <span>Export</span>
              <ChevronDown aria-hidden="true" />
            </button>
            {showExportMenu ? (
              <RecordsMenu onClose={() => setShowExportMenu(false)}>
                <button type="button" role="menuitem" onClick={() => handleExport('csv')}>CSV</button>
                <button type="button" role="menuitem" onClick={() => handleExport('json')}>JSON</button>
              </RecordsMenu>
            ) : null}
          </div>
        </div>
        <div className="records-pagination-controls" aria-label="Records pagination">
          <span className="records-page-range">{visibleStart}-{visibleEnd}</span>
          {selectablePageCount > 1 ? (
            <SlidingPagination
              totalPages={selectablePageCount}
              currentPage={currentPage}
              onPageChange={onPageChange}
              maxVisiblePages={7}
            />
          ) : null}
          <label>
            <span>Rows</span>
            <select value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))} aria-label="Rows per page">
              {[25, 50, 100].map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <button type="button" onClick={onPreviousPage} disabled={!hasPrevious}>Previous</button>
          <button type="button" onClick={onNextPage} disabled={!data?.has_more}>Next</button>
        </div>
      </div>

      <div className="records-table-wrap">
        <table className="records-table" style={{ '--records-table-content-width': tableMinWidth } as CSSProperties}>
          <colgroup>
            <col style={{ width: RECORDS_TABLE_SELECT_COLUMN_WIDTH }} />
            {columnWidths.map((width) => (
              <col key={width.key} style={{ width: width.cssWidth }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th aria-label="Bulk select">
                <input type="checkbox" checked={allVisibleSelected} onChange={toggleAllVisible} aria-label="Select visible records" />
              </th>
              {columns.map((column) => (
                <th key={column.key}>
                  <button type="button" className="records-column-heading" onClick={() => onSort(sortFieldForColumn(column.key))}>
                    <span>{column.label}</span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <AnimatePresence mode="wait" initial={false}>
            <motion.tbody key={rows.map(rowKey).join('|') || 'empty'} initial={reduceMotion ? false : 'hidden'} animate="visible" exit="exit">
              {rows.map((row) => (
                <motion.tr
                  key={rowKey(row)}
                  variants={rowVariants}
                  transition={{ duration: 0.16 }}
                  className={bulkSelection.has(rowKey(row)) ? 'selected' : ''}
                  onClick={() => onSelect(row)}
                >
                  <td onClick={(event) => event.stopPropagation()}>
                    <input type="checkbox" checked={bulkSelection.has(rowKey(row))} onChange={() => toggle(row)} aria-label={`Select ${row.title}`} />
                  </td>
                  {columns.map((column) => (
                    <td key={`${row.id}:${column.key}`}>{cellForColumn(row, column.key, renderValue)}</td>
                  ))}
                </motion.tr>
              ))}
            </motion.tbody>
          </AnimatePresence>
        </table>
      </div>
    </div>
  );
}

function RecordsMenu({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  return (
    <>
      <div className="records-menu-backdrop" onClick={onClose} />
      <div className="records-menu-panel" role="menu">
        {children}
      </div>
    </>
  );
}

function totalForEntity(counts: Record<string, number>, entityFilter: RecordEntityFilter) {
  if (entityFilter !== 'all') return counts[entityFilter] || 0;
  return Object.values(counts).reduce((total, count) => total + Number(count || 0), 0);
}

function cellForColumn(row: RecordsTableRow, columnKey: string, renderValue: (row: RecordsTableRow, columnKey: string) => string) {
  if (columnKey === 'connections') return <ConnectionBadges summary={connectionSummaryForRow(row)} compact />;
  const value = renderValue(row, columnKey);
  if (columnKey === 'name') {
    return (
      <span className="records-person-pill">
        <User aria-hidden="true" />
        <span>{value}</span>
      </span>
    );
  }
  if (columnKey === 'type' || columnKey === 'status_stage') {
    return <span className={`records-status-pill ${statusClass(value)}`}>{value}</span>;
  }
  if (columnKey.includes('email') && value) {
    return <a href={`mailto:${value}`} onClick={(event) => event.stopPropagation()}>{value}</a>;
  }
  return value || '-';
}

function ConnectionBadges({ summary, compact = false }: { summary: ConnectionSummary; compact?: boolean }) {
  const badges = Array.isArray(summary.badges) ? summary.badges.filter((badge) => badge?.label) : [];
  if (!badges.length) return <span className="connection-empty">-</span>;
  return (
    <span className={`connection-badges ${compact ? 'compact' : ''}`} title={connectionTitle(summary)}>
      {badges.slice(0, compact ? 4 : 6).map((badge) => (
        <span key={badge.key || badge.label} className={`connection-badge ${badge.kind || ''}`}>
          {badge.label}
        </span>
      ))}
    </span>
  );
}

function connectionSummaryForRow(row: RecordsTableRow): ConnectionSummary {
  const summary = row.computed?.connection_summary;
  return summary && typeof summary === 'object' && !Array.isArray(summary) ? summary as ConnectionSummary : {};
}

function connectionTitle(summary: ConnectionSummary) {
  const parts = [
    summary.mail_count ? `${summary.mail_count} mail` : '',
    summary.calendar_count ? `${summary.calendar_count} calendar` : '',
    summary.file_count ? `${summary.file_count} files` : '',
    summary.agent_count ? `${summary.agent_count} agent` : '',
    summary.approval_count ? `${summary.approval_count} approvals` : ''
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'No linked business context';
}

function statusClass(value: string) {
  const normalized = value.toLowerCase();
  if (normalized.includes('won') || normalized.includes('priority') || normalized.includes('active')) return 'strong';
  if (normalized.includes('new') || normalized.includes('open') || normalized.includes('discovery')) return 'good';
  if (normalized.includes('lost') || normalized.includes('archived')) return 'weak';
  return '';
}

function csvForRows(rows: RecordsTableRow[], columns: RecordsTableColumn[], renderValue: (row: RecordsTableRow, columnKey: string) => string) {
  const headers = columns.map((column) => column.label);
  const lines = rows.map((row) => columns.map((column) => csvCell(renderValue(row, column.key))).join(','));
  return [headers.map(csvCell).join(','), ...lines].join('\n');
}

function csvCell(value: unknown) {
  return `"${String(value ?? '').replace(/"/g, '""')}"`;
}

function rowKey(row: RecordsTableRow) {
  return `${row.entity_type}:${row.id}`;
}

function widthForColumn(
  column: RecordsTableColumn,
  rows: RecordsTableRow[],
  renderValue: (row: RecordsTableRow, columnKey: string) => string
) {
  const longestContent = rows.reduce((longest, row) => Math.max(longest, lengthForColumnValue(row, column.key, renderValue)), column.label.length);
  const preferredCh = Math.min(
    RECORDS_TABLE_MAX_COLUMN_CH,
    Math.max(RECORDS_TABLE_MIN_COLUMN_CH, longestContent + RECORDS_TABLE_CELL_BUFFER_CH)
  );
  return {
    key: column.key,
    preferredCh,
    cssWidth: `clamp(${RECORDS_TABLE_MIN_COLUMN_CH}ch, ${preferredCh}ch, var(--records-table-column-max-width))`
  };
}

function lengthForColumnValue(
  row: RecordsTableRow,
  columnKey: string,
  renderValue: (row: RecordsTableRow, columnKey: string) => string
) {
  const value = renderValue(row, columnKey).trim();
  if (columnKey === 'name') return value.length + 3;
  if (columnKey === 'connections') return value.length + 2;
  return value.length;
}
