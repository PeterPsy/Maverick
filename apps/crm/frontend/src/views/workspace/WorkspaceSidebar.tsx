import { PanelsTopLeft, X } from 'lucide-react';
import { productNavigation } from '../../domain/navigation';
import { ViewId } from '../../domain/types';

export function WorkspaceSidebar({ view, navigate, open, close, counts }: { view: ViewId; navigate: (view: ViewId) => void; open: boolean; close: () => void; counts: Record<string, number> }) {
  const tables: Partial<Record<ViewId, string>> = { people: 'contacts', companies: 'accounts', deals: 'deals', conversations: 'conversation_threads', expenses: 'expenses', intelligence: 'intelligence_profiles' };
  return <aside className={`product-sidebar ${open ? 'is-open' : ''}`}>
    <header><span className="product-mark"><PanelsTopLeft size={22} /></span><div><strong>Maverick</strong><small>Relationship workspace</small></div><button className="product-mobile-close" aria-label="Close navigation" onClick={close}><X size={18} /></button></header>
    <nav aria-label="CRM workspace">
      {productNavigation.filter((item) => !item.secondary).map(({ page, label, icon: Icon }) => <button key={page} aria-label={label} aria-current={view === page ? 'page' : undefined} onClick={() => navigate(page)}><Icon size={17} /><span>{label}</span>{tables[page] && counts[tables[page]!] !== undefined ? <small className="product-nav-count" title="Active records">{counts[tables[page]!]}</small> : null}</button>)}
      <details open={productNavigation.some((item) => item.page === view && item.secondary) || undefined}><summary>Workspace tools</summary>{productNavigation.filter((item) => item.secondary).map(({ page, label, icon: Icon }) => <button key={page} aria-label={label} aria-current={view === page ? 'page' : undefined} onClick={() => navigate(page)}><Icon size={16} /><span>{label}</span></button>)}</details>
    </nav>
    <footer><span className="product-avatar">M</span><div><strong>CRM</strong><small>Private workspace · Maverick</small></div></footer>
  </aside>;
}
