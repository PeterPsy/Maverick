import { dueLabel, formatMoney, daysFromToday } from '../format';
import { Icon } from '../Icon';
import { labelFor, PAYMENT_OPTIONS, PHASE_OPTIONS } from '../options';
import type { Collaboration } from '../types';

export function WorkRow({ item, onOpen, compact = false }: { item: Collaboration; onOpen: () => void; compact?: boolean }) {
  const urgent = daysFromToday(item.due_date) < 0 || item.payment_status === 'overdue';
  const openDeliverables = item.deliverables.filter((entry) => entry.status !== 'published').length;
  const rightsAlert = daysFromToday(item.rights_expiry_date) <= 7;
  const contractAlert = ['confirmed', 'production'].includes(item.phase) && !['signed', 'not_needed'].includes(item.contract_status);
  const detail = rightsAlert
    ? `Diritti: ${dueLabel(item.rights_expiry_date)}`
    : contractAlert
      ? 'Contratto da firmare'
      : openDeliverables
        ? `${openDeliverables} deliverable aperti`
        : 'Nessun deliverable aperto';
  return (
    <button className={`work-row ${compact ? 'is-compact' : ''}`} onClick={onOpen} type="button">
      <span className="work-row__identity">
        <span className="work-row__title">{item.title}</span>
        <span className="work-row__partner">{item.partner || 'Senza partner'}</span>
      </span>
      <span className="work-row__phase" data-phase={item.phase}>{labelFor(PHASE_OPTIONS, item.phase)}</span>
      <span className="work-row__action">
        <span>{item.next_action || 'Definisci la prossima azione'}</span>
        <small className={rightsAlert || contractAlert ? 'is-warning' : ''}>{detail}</small>
      </span>
      <span className={`work-row__due ${urgent ? 'is-urgent' : ''}`}>{dueLabel(item.due_date)}</span>
      {!compact && <span className="work-row__money">
        <span>{item.value_minor ? formatMoney(item.value_minor, true) : '—'}</span>
        <small className={item.payment_status === 'overdue' ? 'is-danger' : ''}>{labelFor(PAYMENT_OPTIONS, item.payment_status)}</small>
      </span>}
      <Icon name="arrow" size={17} />
    </button>
  );
}
