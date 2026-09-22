import { PanelsTopLeft } from 'lucide-react';
import { productNavigation } from '../../domain/navigation';
import { ViewId } from '../../domain/types';

const countTables: Partial<Record<ViewId, string>> = {
  leads: 'leads',
  people: 'contacts', companies: 'accounts', deals: 'deals',
  conversations: 'conversation_threads', expenses: 'expenses', intelligence: 'intelligence_profiles',
};

export function WorkspaceSidebar({ view, navigate, counts, countsError, retry }: {
  view: ViewId;
  navigate: (view: ViewId) => void;
  counts: Record<string, number>;
  countsError: boolean;
  retry: () => void;
}) {
  function navigationItem({ page, label, icon: Icon, secondary }: typeof productNavigation[number]) {
    const count = counts[countTables[page] || ''];
    return <button key={page} aria-label={label} aria-current={view === page ? 'page' : undefined} onClick={() => navigate(page)}>
      <Icon size={secondary ? 16 : 17} aria-hidden="true" />
      <span>{label}</span>
      {count !== undefined ? <small className="product-nav-count" title="Active records">{count}</small> : null}
    </button>;
  }

  return <aside className="product-sidebar">
    <header>
      <span className="product-mark"><PanelsTopLeft size={22} aria-hidden="true" /></span>
      <div><strong>Maverick</strong><small>Relationship workspace</small></div>
    </header>
    <nav aria-label="CRM workspace">
      {productNavigation.filter((item) => !item.secondary).map(navigationItem)}
      <details open={productNavigation.some((item) => item.page === view && item.secondary) || undefined}>
        <summary>Workspace tools</summary>
        {productNavigation.filter((item) => item.secondary).map(navigationItem)}
      </details>
    </nav>
    {countsError ? <div className="sidebar-count-error" role="status">Counts unavailable. <button onClick={retry}>Retry counts</button></div> : null}
  </aside>;
}
