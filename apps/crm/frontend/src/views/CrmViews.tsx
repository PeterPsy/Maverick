import { MoreHorizontal, Search } from 'lucide-react';

export function WorkspaceTopbar({
  query,
  selectedCount,
  onBulkArchive,
  onBulkTag,
  onQueryChange
}: {
  query: string;
  selectedCount: number;
  onBulkArchive: () => void;
  onBulkTag: () => void;
  onQueryChange: (value: string) => void;
}) {
  return (
    <header className="crm-topbar">
      <label className="crm-search">
        <Search size={17} aria-hidden="true" />
        <input aria-label="Search CRM" onChange={(event) => onQueryChange(event.target.value)} placeholder="Search CRM" value={query} />
      </label>
      <div className="topbar-actions">
        {selectedCount ? (
          <details className="bulk-actions">
            <summary aria-label="Bulk actions" title="Bulk actions">
              <MoreHorizontal size={15} aria-hidden="true" />
              <span>{selectedCount} selected</span>
            </summary>
            <div className="toolbar-admin-popover bulk-actions__menu" role="menu" aria-label="Bulk actions">
              <button type="button" role="menuitem" onClick={onBulkTag}>Tag selected records</button>
              <button type="button" role="menuitem" onClick={onBulkArchive}>Archive selected records</button>
            </div>
          </details>
        ) : null}
      </div>
    </header>
  );
}
