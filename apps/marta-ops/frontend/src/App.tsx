import { useMemo, useState } from 'react';
import { Icon } from './Icon';
import { IdeasView } from './components/IdeasView';
import { TodayView } from './components/TodayView';
import { WorkPanel } from './components/WorkPanel';
import { WorksView } from './components/WorksView';
import type { Collaboration, Idea, ViewId } from './types';
import { useMartaOps } from './useMartaOps';

const NAV: Array<[ViewId, string, 'today' | 'work' | 'ideas']> = [
  ['today', 'Oggi', 'today'],
  ['work', 'Lavori', 'work'],
  ['ideas', 'Idee', 'ideas']
];

export function App() {
  const { state, loading, saving, error, clearError, mutate } = useMartaOps();
  const [view, setView] = useState<ViewId>('today');
  const [query, setQuery] = useState('');
  const [panelOpen, setPanelOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = useMemo(() => state.collaborations.find((item) => item.id === selectedId) ?? null, [selectedId, state.collaborations]);

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
        <button aria-label="Marta Ops" className="brand" onClick={() => setView('today')} type="button"><span className="brand-mark">M</span><span>Marta Ops</span></button>
        <nav className="desktop-nav" aria-label="Sezioni">
          {NAV.map(([id, label, icon]) => <button className={view === id ? 'is-active' : ''} key={id} onClick={() => setView(id)} type="button"><Icon name={icon} size={17} />{label}</button>)}
        </nav>
        <div className="topbar-actions">
          <label className="app-search"><Icon name="search" size={17} /><input aria-label="Cerca lavori" onChange={(event) => { setQuery(event.target.value); if (event.target.value) setView('work'); }} placeholder="Cerca" value={query} /></label>
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
        {NAV.map(([id, label, icon]) => <button className={view === id ? 'is-active' : ''} key={id} onClick={() => setView(id)} type="button"><Icon name={icon} size={19} /><span>{label}</span></button>)}
      </nav>

      {panelOpen && <WorkPanel
        item={selected}
        onAddDeliverable={async (collaborationId, deliverable) => { await mutate({ action: 'add_deliverable', collaboration_id: collaborationId, deliverable }); }}
        onClose={() => setPanelOpen(false)}
        onSave={saveWork}
        onUpdateDeliverable={async (collaborationId, id, changes) => { await mutate({ action: 'update_deliverable', collaboration_id: collaborationId, id, changes }); }}
        saving={saving}
      />}
      {error && <div className="toast" role="alert"><span>{error}</span><button aria-label="Chiudi messaggio" onClick={clearError} type="button"><Icon name="close" size={16} /></button></div>}
    </div>
  );
}
