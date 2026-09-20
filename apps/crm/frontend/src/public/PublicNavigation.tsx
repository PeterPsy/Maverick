import { useState } from 'react';
import { Menu, X } from 'lucide-react';
import { ViewId } from '../domain/types';
import { useLiveCrm } from '../domain/vnext';
import { WorkspaceSidebar } from '../widgets/crm-sidebar/WorkspaceSidebar';
import '../widgets/crm-sidebar/sidebar.css';
import './public.css';

export function PublicNavigation({ view, navigate }: { view: ViewId; navigate: (page: ViewId) => void }) {
  const [open, setOpen] = useState(false);
  const counts = useLiveCrm<{ counts: Record<string, number> }>({ action: 'crm.workspace_view', view: 'sidebar' });
  return <div className={`crm-public-navigation ${open ? 'is-open' : ''}`}>
    <button className="crm-public-menu" aria-label={open ? 'Close navigation' : 'Open navigation'} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? <X /> : <Menu />}</button>
    <WorkspaceSidebar view={view} navigate={page => { navigate(page); setOpen(false); }} counts={counts.data?.counts || {}}
      countsError={Boolean(counts.error)} retry={counts.refresh} />
  </div>;
}
