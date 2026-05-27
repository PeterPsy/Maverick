import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ArrowUpDown, ChevronDown, Download, Filter, User } from 'lucide-react';
import { RecordsTableColumn, RecordsTablePayload, RecordsTableRow } from '../../api';
import { RecordEntityFilter } from '../../domain/types';
import { entityLabel, recordEntityFilters } from '../../domain/routing';

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
          <label>
            <span>Page</span>
            <select value={currentPage} onChange={(event) => onPageChange(Number(event.target.value))} aria-label="Records page">
              {Array.from({ length: selectablePageCount }, (_, index) => index + 1).map((page) => (
                <option key={page} value={page}>{page}</option>
              ))}
            </select>
            <span>of {totalPages}</span>
          </label>
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
        <table className="records-table">
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
