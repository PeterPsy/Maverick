import { FormEvent, MouseEvent, useEffect, useState } from 'react';
import { Icon } from '../Icon';
import { CONTRACT_OPTIONS, DELIVERABLE_OPTIONS, KIND_OPTIONS, PAYMENT_OPTIONS, PHASE_OPTIONS } from '../options';
import type { Collaboration, DeliverableStatus, WorkDraft } from '../types';

const EMPTY_DRAFT: WorkDraft = {
  title: '', partner: '', partner_email: '', kind: 'partnership', phase: 'lead', next_action: '', due_date: '', value_euros: '',
  payment_status: 'not_due', contract_status: 'not_needed', rights_expiry_date: '', notes: ''
};

function draftFor(item: Collaboration | null): WorkDraft {
  if (!item) return { ...EMPTY_DRAFT };
  return {
    title: item.title,
    partner: item.partner,
    partner_email: item.partner_email || '',
    kind: item.kind,
    phase: item.phase,
    next_action: item.next_action,
    due_date: item.due_date,
    value_euros: item.value_minor ? (item.value_minor / 100).toFixed(2) : '',
    payment_status: item.payment_status,
    contract_status: item.contract_status,
    rights_expiry_date: item.rights_expiry_date,
    notes: item.notes
  };
}

export function WorkPanel({ item, saving, onClose, onSave, onIntegrate, onAddDeliverable, onUpdateDeliverable }: {
  item: Collaboration | null;
  saving: boolean;
  onClose: () => void;
  onSave: (id: string | null, changes: Record<string, unknown>) => Promise<void>;
  onIntegrate: (id: string, target: 'mail' | 'calendar') => Promise<void>;
  onAddDeliverable: (collaborationId: string, deliverable: { title: string; due_date: string }) => Promise<void>;
  onUpdateDeliverable: (collaborationId: string, deliverableId: string, changes: Record<string, unknown>) => Promise<void>;
}) {
  const [draft, setDraft] = useState<WorkDraft>(() => draftFor(item));
  const [deliverableTitle, setDeliverableTitle] = useState('');
  const [deliverableDate, setDeliverableDate] = useState('');
  const [integrationBusy, setIntegrationBusy] = useState<'mail' | 'calendar' | null>(null);
  const [integrationMessage, setIntegrationMessage] = useState('');

  useEffect(() => { setDraft(draftFor(item)); setIntegrationMessage(''); }, [item]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const set = <K extends keyof WorkDraft>(key: K, value: WorkDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));

  function normalizedDraft() {
    const { value_euros, ...fields } = draft;
    const normalized = Number(value_euros.replace(',', '.'));
    return { ...fields, value_minor: Number.isFinite(normalized) ? Math.round(normalized * 100) : 0 };
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await onSave(item?.id ?? null, normalizedDraft());
      onClose();
    } catch {
      // The app-level error toast owns user feedback.
    }
  }

  async function runIntegration(target: 'mail' | 'calendar') {
    if (!item) return;
    setIntegrationBusy(target);
    setIntegrationMessage('');
    try {
      await onSave(item.id, normalizedDraft());
      await onIntegrate(item.id, target);
      setIntegrationMessage(target === 'mail' ? 'Bozza pronta in Mail. Nessun messaggio è stato inviato.' : 'Scadenza aggiunta al Calendario.');
    } catch {
      // The app-level error toast owns error feedback.
    } finally {
      setIntegrationBusy(null);
    }
  }

  async function addDeliverable(event: FormEvent) {
    event.preventDefault();
    if (!item || !deliverableTitle.trim()) return;
    try {
      await onAddDeliverable(item.id, { title: deliverableTitle, due_date: deliverableDate });
      setDeliverableTitle(''); setDeliverableDate('');
    } catch {
      // Keep the draft in place when persistence fails.
    }
  }

  function backdrop(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) onClose();
  }

  return (
    <div className="panel-backdrop" onMouseDown={backdrop}>
      <aside aria-labelledby="work-panel-title" aria-modal="true" className={`work-panel ${item ? 'has-deliverables' : 'is-new'}`} role="dialog">
        <header className="panel-header">
          <div><p className="eyebrow">{item ? 'Dettaglio lavoro' : 'Nuovo lavoro'}</p><h2 id="work-panel-title">{item?.title || 'Aggiungi ciò che conta'}</h2></div>
          <button aria-label="Chiudi" className="icon-action" onClick={onClose} type="button"><Icon name="close" /></button>
        </header>

        <form className="work-form" id="work-form" onSubmit={submit}>
          <div className="form-grid">
            <label className="field is-wide"><span>Titolo</span><input autoFocus={!item} maxLength={160} onChange={(event) => set('title', event.target.value)} placeholder="Es. Partnership autunno" required value={draft.title} /></label>
            <label className="field"><span>Partner</span><input maxLength={160} onChange={(event) => set('partner', event.target.value)} placeholder="Brand o progetto" value={draft.partner} /></label>
            <label className="field"><span>Email partner</span><input maxLength={320} onChange={(event) => set('partner_email', event.target.value)} placeholder="contatto@brand.it" type="email" value={draft.partner_email} /></label>
            <label className="field"><span>Tipo</span><select onChange={(event) => set('kind', event.target.value as WorkDraft['kind'])} value={draft.kind}>{KIND_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="field"><span>Fase</span><select onChange={(event) => set('phase', event.target.value as WorkDraft['phase'])} value={draft.phase}>{PHASE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="field is-wide"><span>Prossima azione</span><input maxLength={240} onChange={(event) => set('next_action', event.target.value)} placeholder="Una frase concreta: chi fa cosa?" value={draft.next_action} /></label>
            <label className="field"><span>Scadenza</span><input onChange={(event) => set('due_date', event.target.value)} type="date" value={draft.due_date} /></label>
            <label className="field"><span>Valore €</span><input inputMode="decimal" onChange={(event) => set('value_euros', event.target.value)} placeholder="0,00" value={draft.value_euros} /></label>
            <label className="field"><span>Pagamento</span><select onChange={(event) => set('payment_status', event.target.value as WorkDraft['payment_status'])} value={draft.payment_status}>{PAYMENT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="field"><span>Contratto</span><select onChange={(event) => set('contract_status', event.target.value as WorkDraft['contract_status'])} value={draft.contract_status}>{CONTRACT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="field"><span>Scadenza diritti</span><input onChange={(event) => set('rights_expiry_date', event.target.value)} type="date" value={draft.rights_expiry_date} /></label>
            <label className="field is-wide"><span>Note</span><textarea maxLength={4000} onChange={(event) => set('notes', event.target.value)} placeholder="Solo informazioni operative utili" rows={3} value={draft.notes} /></label>
          </div>
        </form>

        {item && <section className="integrations-section">
          <div className="section-heading"><h3>Azioni collegate</h3></div>
          <div className="integration-actions">
            <button className="secondary-action" disabled={saving || !draft.partner_email} onClick={() => void runIntegration('mail')} type="button"><Icon name="mail" size={16} />{integrationBusy === 'mail' ? 'Creo la bozza…' : 'Crea bozza Mail'}</button>
            <button className="secondary-action" disabled={saving || !draft.due_date} onClick={() => void runIntegration('calendar')} type="button"><Icon name="calendar" size={16} />{integrationBusy === 'calendar' ? 'Aggiungo…' : 'Aggiungi al Calendario'}</button>
          </div>
          <p aria-live="polite" className={integrationMessage ? 'integration-feedback is-success' : 'integration-feedback'}>{integrationMessage || (!draft.partner_email ? 'Aggiungi l’email del partner per preparare una bozza.' : !draft.due_date ? 'Aggiungi una scadenza per creare l’evento.' : 'Le modifiche vengono salvate prima di eseguire l’azione.')}</p>
        </section>}

        {item && <section className="deliverables-section">
          <div className="section-heading"><h3>Deliverable</h3><span>{item.deliverables.length}</span></div>
          <div className="deliverable-list">
            {item.deliverables.map((deliverable) => <div className="deliverable-row" key={deliverable.id}>
              <button aria-label={deliverable.status === 'published' ? 'Riapri deliverable' : 'Segna come pubblicato'} className={`deliverable-check ${deliverable.status === 'published' ? 'is-done' : ''}`} onClick={() => void onUpdateDeliverable(item.id, deliverable.id, { status: deliverable.status === 'published' ? 'planned' : 'published' }).catch(() => undefined)} type="button">{deliverable.status === 'published' && <Icon name="check" size={15} />}</button>
              <div><strong>{deliverable.title}</strong><small>{deliverable.due_date || 'Nessuna data'}</small></div>
              <select aria-label={`Stato di ${deliverable.title}`} onChange={(event) => void onUpdateDeliverable(item.id, deliverable.id, { status: event.target.value as DeliverableStatus }).catch(() => undefined)} value={deliverable.status}>
                {DELIVERABLE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </div>)}
          </div>
          <form className="deliverable-add" onSubmit={addDeliverable}>
            <input aria-label="Nuovo deliverable" maxLength={180} onChange={(event) => setDeliverableTitle(event.target.value)} placeholder="Aggiungi un deliverable…" value={deliverableTitle} />
            <input aria-label="Scadenza deliverable" onChange={(event) => setDeliverableDate(event.target.value)} type="date" value={deliverableDate} />
            <button className="secondary-action" disabled={saving || !deliverableTitle.trim()} type="submit">Aggiungi</button>
          </form>
        </section>}

        <footer className="panel-footer"><button className="secondary-action" onClick={onClose} type="button">Annulla</button><button className="primary-action" disabled={saving} form="work-form" type="submit">{saving ? 'Salvataggio…' : item ? 'Salva modifiche' : 'Crea lavoro'}</button></footer>
      </aside>
    </div>
  );
}
