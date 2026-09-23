import { daysFromToday, formatMoney, todayIso } from '../format';
import type { Collaboration } from '../types';
import { WorkRow } from './WorkRow';

const CLOSED = new Set(['completed', 'lost']);

export function TodayView({ items, onCreate, onOpen }: { items: Collaboration[]; onCreate: () => void; onOpen: (item: Collaboration) => void }) {
  const active = items.filter((item) => !CLOSED.has(item.phase));
  const focus = active
    .filter((item) => daysFromToday(item.due_date) <= 1
      || item.payment_status === 'overdue'
      || item.phase === 'approval'
      || daysFromToday(item.rights_expiry_date) <= 7
      || (['confirmed', 'production'].includes(item.phase) && !['signed', 'not_needed'].includes(item.contract_status)))
    .sort((a, b) => daysFromToday(a.due_date) - daysFromToday(b.due_date));
  const upcoming = active
    .filter((item) => daysFromToday(item.due_date) > 1 && daysFromToday(item.due_date) <= 7)
    .sort((a, b) => daysFromToday(a.due_date) - daysFromToday(b.due_date));
  const toCollect = active
    .filter((item) => ['invoiced', 'overdue'].includes(item.payment_status))
    .reduce((sum, item) => sum + item.value_minor, 0);
  const dateLabel = new Intl.DateTimeFormat('it-IT', { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date(`${todayIso()}T12:00:00`));

  return (
    <section className="page today-page">
      <header className="page-heading">
        <div><p className="eyebrow">{dateLabel}</p><h1>Oggi</h1></div>
        <p className="page-heading__note">Solo ciò che richiede attenzione.</p>
      </header>

      <div className="metric-strip" aria-label="Sintesi operativa">
        <div><span>{focus.length}</span><small>da gestire</small></div>
        <div><span>{upcoming.length}</span><small>entro 7 giorni</small></div>
        <div><span>{formatMoney(toCollect, true)}</span><small>da incassare</small></div>
      </div>

      {items.length > 0 && <section className="work-section">
        <div className="section-heading"><h2>Focus</h2><span>{focus.length}</span></div>
        {focus.length ? (
          <div className="row-list">{focus.map((item) => <WorkRow compact item={item} key={item.id} onOpen={() => onOpen(item)} />)}</div>
        ) : (
          <div className="empty-state is-inline"><p>Nessuna urgenza. Ottimo momento per preparare il prossimo lavoro.</p><button className="text-action" onClick={onCreate} type="button">Aggiungi un lavoro</button></div>
        )}
      </section>}

      {upcoming.length > 0 && <section className="work-section">
        <div className="section-heading"><h2>Prossimi 7 giorni</h2><span>{upcoming.length}</span></div>
        <div className="row-list">{upcoming.map((item) => <WorkRow compact item={item} key={item.id} onOpen={() => onOpen(item)} />)}</div>
      </section>}

      {!items.length && <div className="empty-state welcome-state">
        <span className="welcome-mark">M</span>
        <h2>Un solo posto per sapere cosa viene dopo.</h2>
        <p>Inserisci la prima collaborazione. Marta Ops mostrerà azioni, scadenze, deliverable e incassi senza rumore.</p>
        <button className="primary-action" onClick={onCreate} type="button">Crea il primo lavoro</button>
      </div>}
    </section>
  );
}
