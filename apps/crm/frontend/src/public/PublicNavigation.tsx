import { useLayoutEffect, useState } from 'react';
import { Menu, Moon, Sun, X } from 'lucide-react';
import { ViewId } from '../domain/types';
import { useLiveCrm } from '../domain/vnext';
import { WorkspaceSidebar } from '../widgets/crm-sidebar/WorkspaceSidebar';
import sidebarLogoDark from '../../../../base-shell/frontend/public/sidebar-logo.svg';
import sidebarLogoLight from '../../../../base-shell/frontend/public/sidebar-logo-black.svg';
import '../widgets/crm-sidebar/sidebar.css';
import './public.css';

type PublicTheme = 'dark' | 'light';

const PUBLIC_THEME_KEY = 'maverick:crm-public:theme';

function readPublicTheme(): PublicTheme {
  try {
    const saved = window.localStorage.getItem(PUBLIC_THEME_KEY);
    if (saved === 'dark' || saved === 'light') return saved;
  } catch {
    // Storage can be unavailable in privacy-restricted browsers.
  }
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function PublicNavigation({ view, navigate }: { view: ViewId; navigate: (page: ViewId) => void }) {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<PublicTheme>(readPublicTheme);
  const counts = useLiveCrm<{ counts: Record<string, number> }>({ action: 'crm.workspace_view', view: 'sidebar' });

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.maverickTheme = theme;
    document.documentElement.style.colorScheme = theme;
    try { window.localStorage.setItem(PUBLIC_THEME_KEY, theme); } catch { /* See readPublicTheme. */ }
  }, [theme]);

  return <>
    <button className="crm-public-menu" aria-label={open ? 'Close navigation' : 'Open navigation'} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? <X /> : <Menu />}</button>
    <aside className={`crm-public-navigation ${open ? 'is-open' : ''}`} aria-label="CRM navigation">
      <div className="crm-public-sidebar-frame">
        <div className="crm-public-sidebar-body">
          <WorkspaceSidebar view={view} navigate={page => { navigate(page); setOpen(false); }} counts={counts.data?.counts || {}}
            countsError={Boolean(counts.error)} retry={counts.refresh} />
        </div>
        <footer className="crm-public-sidebar-footer">
          <img alt="" aria-hidden="true" className="crm-public-sidebar-logo" src={theme === 'light' ? sidebarLogoLight : sidebarLogoDark} />
          <div className="crm-public-theme-switcher" aria-label="Theme mode">
            <button aria-label="Dark mode" aria-pressed={theme === 'dark'} className={theme === 'dark' ? 'is-active' : ''} onClick={() => setTheme('dark')} type="button"><Moon aria-hidden="true" /></button>
            <button aria-label="Light mode" aria-pressed={theme === 'light'} className={theme === 'light' ? 'is-active' : ''} onClick={() => setTheme('light')} type="button"><Sun aria-hidden="true" /></button>
          </div>
        </footer>
      </div>
    </aside>
  </>;
}
