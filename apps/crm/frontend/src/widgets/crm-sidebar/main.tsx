import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BarChart3, Handshake, Rows3 } from 'lucide-react';
import './styles.css';

const nav = [
  { label: 'Records', page: 'records', icon: Rows3 },
  { label: 'Pipeline', page: 'pipeline', icon: Handshake },
  { label: 'Reports', page: 'reports', icon: BarChart3 }
];

const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';

function isMobileLayoutViewport() {
  if (typeof window === 'undefined') {
    return false;
  }
  try {
    const shellWindow = window.parent && window.parent !== window ? window.parent : window;
    return typeof shellWindow.matchMedia === 'function' && shellWindow.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  } catch {
    return typeof window.matchMedia === 'function' && window.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  }
}

function useShellMobileLayout() {
  const [isShellMobileLayout, setIsShellMobileLayout] = useState(isMobileLayoutViewport);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    let mediaQuery: MediaQueryList;
    try {
      const shellWindow = window.parent && window.parent !== window ? window.parent : window;
      mediaQuery = shellWindow.matchMedia(MOBILE_LAYOUT_QUERY);
    } catch {
      mediaQuery = window.matchMedia(MOBILE_LAYOUT_QUERY);
    }
    const update = () => setIsShellMobileLayout(mediaQuery.matches);
    update();
    mediaQuery.addEventListener('change', update);
    return () => mediaQuery.removeEventListener('change', update);
  }, []);

  return isShellMobileLayout;
}

function openCrm(page = '') {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'crm',
      params: page ? { app_page: page } : {}
    },
    window.location.origin
  );
}

function CrmSidebar() {
  const isShellMobileLayout = useShellMobileLayout();

  return (
    <main className={`crm-sidebar-widget ${isShellMobileLayout ? 'is-shell-mobile' : ''}`}>
      <div className="crm-sidebar-list">
        <nav>
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button className="crm-sidebar-row" key={item.label} onClick={() => openCrm(item.page)}>
                <Icon size={15} aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>
    </main>
  );
}

createRoot(document.getElementById('crm-sidebar-root')!).render(<CrmSidebar />);
