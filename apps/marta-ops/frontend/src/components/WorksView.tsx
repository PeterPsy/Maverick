import { useMemo, useState } from 'react';
import type { Collaboration } from '../types';
import { WorkRow } from './WorkRow';

type Filter = 'open' | 'all' | 'closed';
const CLOSED = new Set(['completed', 'lost']);

export function WorksView({ items, query, onCreate, onOpen }: { items: Collaboration[]; query: string; onCreate: () => void; onOpen: (item: Collaboration) => void }) {
  const [filter, setFilter] = useState<Filter>('open');
  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('it');
    return items
      .filter((item) => filter === 'all' || (filter === 'closed' ? CLOSED.has(item.phase) : !CLOSED.has(item.phase)))
      .filter((item) => !needle || [item.title, item.partner, item.next_action].some((value) => value.toLocaleLowerCase('it').includes(needle)))
      .sort((a, b) => (a.due_date || '9999').localeCompare(b.due_date || '9999'));
  }, [filter, items, query]);

  return (
    <section className="page works-page">
      <header className="page-heading">
        <div><p className="eyebrow">Collaborazioni e progetti</p><h1>Lavori</h1></div>
        <button className="secondary-action page-create" onClick={onCreate} type="button">Nuovo lavoro</button>
      </header>
      <div className="filter-tabs" role="tablist">
        {([['open', 'Aperti'], ['all', 'Tutti'], ['closed', 'Chiusi']] as Array<[Filter, string]>).map(([value, label]) => (
          <button aria-selected={filter === value} className={filter === value ? 'is-active' : ''} key={value} onClick={() => setFilter(value)} role="tab" type="button">{label}</button>
        ))}
      </div>
      <div className="list-header" aria-hidden="true"><span>Lavoro</span><span>Fase</span><span>Prossima azione</span><span>Data</span><span>Valore</span><span /></div>
      {visible.length ? <div className="row-list work-table">{visible.map((item) => <WorkRow item={item} key={item.id} onOpen={() => onOpen(item)} />)}</div> : (
        <div className="empty-state"><h2>Nessun lavoro qui</h2><p>{query ? 'Prova una ricerca diversa.' : 'Crea un lavoro e assegna subito la prossima azione.'}</p>{!query && <button className="primary-action" onClick={onCreate} type="button">Nuovo lavoro</button>}</div>
      )}
    </section>
  );
}
