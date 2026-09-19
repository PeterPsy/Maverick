import { useEffect, useRef } from 'react';
import { Menu, MoreHorizontal, Plus, RefreshCw, Search } from 'lucide-react';

export function WorkspaceTopbar({
  onMenu, onRefresh, onCreate,
  query,
  selectedCount,
  onBulkArchive,
  onBulkTag,
  onQueryChange
}: {
  onMenu: () => void; onRefresh: () => void; onCreate: () => void;
  query: string;
  selectedCount: number;
  onBulkArchive: () => void;
  onBulkTag: () => void;
  onQueryChange: (value: string) => void;
}) {
  const search = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const focus = (event: KeyboardEvent) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); search.current?.focus(); } };
    window.addEventListener('keydown', focus);
    return () => window.removeEventListener('keydown', focus);
  }, []);
  return (
    <header className="crm-topbar">
      <button className="product-menu-toggle" aria-label="Open navigation" onClick={onMenu}><Menu size={20} /></button>
      <label className="crm-search">
        <Search size={17} aria-hidden="true" />
        <input ref={search} aria-label="Search CRM" onChange={(event) => onQueryChange(event.target.value)} placeholder="Search CRM" value={query} />
      </label>
      <div className="topbar-actions">
        <button onClick={onRefresh} aria-label="Refresh workspace"><RefreshCw size={17} /></button>
        <button onClick={onCreate} aria-label="New record"><Plus size={17} /><span>New record</span></button>
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
