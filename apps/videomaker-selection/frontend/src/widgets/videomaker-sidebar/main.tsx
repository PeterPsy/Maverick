import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BriefcaseBusiness, CheckCircle2, CircleUserRound, MailCheck, Users } from 'lucide-react';
import { readStats, readViewState, saveViewState } from '../../api';
import type { Stats, ViewState } from '../../types';
import '../../styles/sidebar-widget.css';

const APP_ID = 'videomaker-selection';
const EMPTY_STATS: Stats = {
  total: 0,
  reviewed: 0,
  favorites: 0,
  due_actions: 0,
  decision: {},
  email: {},
  call: {},
  poc: {}
};

type FilterId = 'all' | 'da_valutare' | 'riserva' | 'selezionato' | 'email_inviata';

function activeFilter(view: ViewState): FilterId | '' {
  if (view.email_status === 'email_inviata' && view.decision === 'all') return 'email_inviata';
  if (view.email_status !== 'all') return '';
  if (view.decision === 'da_valutare' || view.decision === 'riserva' || view.decision === 'selezionato') {
    return view.decision;
  }
  return view.decision === 'all' ? 'all' : '';
}

function SidebarFilters() {
  const [stats, setStats] = useState<Stats>(EMPTY_STATS);
  const [view, setView] = useState<ViewState>({
    mode: 'search', query: '', decision: 'all', email_status: 'all', title: '', refs: []
  });
  const [saving, setSaving] = useState<FilterId | ''>('');
  const [error, setError] = useState('');

  async function refreshStats() {
    try {
      setStats(await readStats());
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Impossibile caricare i filtri.');
    }
  }

  async function refreshView() {
    try {
      setView(await readViewState());
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Impossibile caricare i filtri.');
    }
  }

  useEffect(() => {
    void Promise.all([refreshStats(), refreshView()]);
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { type?: string; owner_app_id?: string; resource?: string };
      if (
        (payload.type !== 'maverick.app.data-changed' && payload.type !== 'maverick.widget.data-changed') ||
        payload.owner_app_id !== APP_ID
      ) return;
      if (!payload.resource || payload.resource === 'candidates') void refreshStats();
      if (!payload.resource || payload.resource === 'view-state') void refreshView();
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, []);

  async function applyFilter(filter: FilterId) {
    setSaving(filter);
    const decision = filter === 'email_inviata' ? 'all' : filter;
    const emailStatus = filter === 'email_inviata' ? 'email_inviata' : 'all';
    try {
      const next = await saveViewState(view.query, decision, emailStatus);
      setView(next);
      setError('');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Filtro non applicato.');
    } finally {
      setSaving('');
    }
  }

  const selected = activeFilter(view);
  const filters = [
    { id: 'all' as const, label: 'Candidature', value: stats.total, icon: Users },
    { id: 'da_valutare' as const, label: 'Da valutare', value: stats.decision.da_valutare || 0, icon: CircleUserRound },
    { id: 'riserva' as const, label: 'In riserva', value: stats.decision.riserva || 0, icon: BriefcaseBusiness },
    { id: 'selezionato' as const, label: 'Selezionati', value: stats.decision.selezionato || 0, icon: CheckCircle2 },
    { id: 'email_inviata' as const, label: 'Email inviate', value: stats.email.email_inviata || 0, icon: MailCheck }
  ];

  return (
    <main className="vm-sidebar vm-sidebar--filters-only">
      <div className="vm-sidebar-filter-list" aria-label="Filtra candidature">
        {filters.map((filter) => (
          <button
            aria-pressed={selected === filter.id}
            className={`vm-sidebar-filter-card ${selected === filter.id ? 'is-active' : ''}`}
            disabled={Boolean(saving)}
            key={filter.id}
            onClick={() => void applyFilter(filter.id)}
            type="button"
          >
            <span className="vm-sidebar-filter-icon"><filter.icon size={18} /></span>
            <span className="vm-sidebar-filter-copy">
              <strong>{filter.value}</strong>
              <small>{filter.label}</small>
            </span>
            <span className="vm-sidebar-filter-state" aria-hidden="true" />
          </button>
        ))}
      </div>
      {error ? <p className="vm-sidebar-empty" role="status">{error}</p> : null}
    </main>
  );
}

createRoot(document.getElementById('videomaker-sidebar-root') as HTMLElement).render(<SidebarFilters />);
