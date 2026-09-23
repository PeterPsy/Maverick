import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Icon } from './Icon';
import { IdeasView } from './components/IdeasView';
import { TodayView } from './components/TodayView';
import { WorkPanel } from './components/WorkPanel';
import { WorksView } from './components/WorksView';
import { isMaverickParentMessage, mountedAppIdFromPath, openApp, postToShell, viewFromAppPage } from './lib/shellNavigation';
import type { Collaboration, Idea, ViewId } from './types';
import { useMartaOps } from './useMartaOps';

const NAV: Array<[ViewId, string, 'today' | 'work' | 'ideas']> = [
  ['today', 'Oggi', 'today'],
  ['work', 'Lavori', 'work'],
  ['ideas', 'Idee', 'ideas']
];

export function App() {
  const { state, loading, saving, error, clearError, integrate, mutate } = useMartaOps();
  const [view, setView] = useState<ViewId>('today');
  const [query, setQuery] = useState('');
  const [panelOpen, setPanelOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const consumedNewWorkRequests = useRef(new Set<string>());
  const consumedLegacyNewWorkRequest = useRef(false);
  const appId = useMemo(() => mountedAppIdFromPath(), []);
  const selected = useMemo(() => state.collaborations.find((item) => item.id === selectedId) ?? null, [selectedId, state.collaborations]);

  const navigate = useCallback((nextView: ViewId) => {
    setView(nextView);
    openApp(appId, { app_page: nextView });
  }, [appId]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (!isMaverickParentMessage(event)) return;
      const message = event.data as {
        app_id?: string;
        params?: Record<string, unknown>;
        type?: string;
      };
      if (message.type !== 'maverick.app.navigate' || (message.app_id && message.app_id !== appId)) return;
      const params = message.params || {};
      const nextView = viewFromAppPage(params.app_page);
      if (nextView) setView(nextView);
      if (params.new_work !== true) return;

      const requestId = typeof params.new_work_request_id === 'string' ? params.new_work_request_id : '';
      if (requestId) {
        if (consumedNewWorkRequests.current.has(requestId)) return;
        consumedNewWorkRequests.current.add(requestId);
      } else if (consumedLegacyNewWorkRequest.current) {
        return;
      } else {
        consumedLegacyNewWorkRequest.current = true;
      }
      setView('work');
      setSelectedId(null);
      setPanelOpen(true);
    }

    window.addEventListener('message', handleShellMessage);
    postToShell({ type: 'maverick.app.ready', app_id: appId });
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId]);

  function openWork(item: Collaboration | null) {
    setSelectedId(item?.id ?? null);
    setPanelOpen(true);
  }

  async function saveWork(id: string | null, changes: Record<string, unknown>) {
    const payload = id
      ? await mutate({ action: 'update_collaboration', id, changes })
      : await mutate({ action: 'create_collaboration', collaboration: changes });
    if (payload.collaboration) setSelectedId(payload.collaboration.id);
  }

  async function createIdea(idea: { title: string; pillar: string; note: string }) {
    await mutate({ action: 'create_idea', idea });
  }

  async function updateIdea(id: string, changes: Partial<Idea>) {
    await mutate({ action: 'update_idea', id, changes });
  }

  return (
    <div className="marta-shell">
      <header className="app-topbar">
        <button aria-label="Marta Ops" className="brand" onClick={() => navigate('today')} type="button"><span className="brand-mark">M</span><span>Marta Ops</span></button>
        <nav className="desktop-nav" aria-label="Sezioni">
          {NAV.map(([id, label, icon]) => <button className={view === id ? 'is-active' : ''} key={id} onClick={() => navigate(id)} type="button"><Icon name={icon} size={17} />{label}</button>)}
        </nav>
        <div className="topbar-actions">
          <label className="app-search"><Icon name="search" size={17} /><input aria-label="Cerca lavori" onChange={(event) => { setQuery(event.target.value); if (event.target.value && view !== 'work') navigate('work'); }} placeholder="Cerca" value={query} /></label>
          <button aria-label="Nuovo lavoro" className="primary-action new-work" onClick={() => openWork(null)} type="button"><Icon name="plus" size={17} /><span>Nuovo lavoro</span></button>
        </div>
      </header>

      <main className="app-content">
        {loading ? <div className="loading-state"><span /><p>Preparo il workspace…</p></div> : <>
          {view === 'today' && <TodayView items={state.collaborations} onCreate={() => openWork(null)} onOpen={openWork} />}
          {view === 'work' && <WorksView items={state.collaborations} onCreate={() => openWork(null)} onOpen={openWork} query={query} />}
          {view === 'ideas' && <IdeasView ideas={state.ideas} onCreate={createIdea} onUpdate={updateIdea} saving={saving} />}
        </>}
      </main>

      <nav className="mobile-nav" aria-label="Sezioni">
        {NAV.map(([id, label, icon]) => <button className={view === id ? 'is-active' : ''} key={id} onClick={() => navigate(id)} type="button"><Icon name={icon} size={19} /><span>{label}</span></button>)}
      </nav>

      {panelOpen && <WorkPanel
        item={selected}
        onAddDeliverable={async (collaborationId, deliverable) => { await mutate({ action: 'add_deliverable', collaboration_id: collaborationId, deliverable }); }}
        onClose={() => setPanelOpen(false)}
        onIntegrate={async (id, target) => {
          await integrate({ action: target === 'mail' ? 'create_mail_draft' : 'create_calendar_event', id });
        }}
        onSave={saveWork}
        onUpdateDeliverable={async (collaborationId, id, changes) => { await mutate({ action: 'update_deliverable', collaboration_id: collaborationId, id, changes }); }}
        saving={saving}
      />}
      {error && <div className="toast" role="alert"><span>{error}</span><button aria-label="Chiudi messaggio" onClick={clearError} type="button"><Icon name="close" size={16} /></button></div>}
    </div>
  );
}
