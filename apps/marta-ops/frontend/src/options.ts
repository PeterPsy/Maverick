import type { CollaborationKind, CollaborationPhase, ContractStatus, DeliverableStatus, IdeaStatus, PaymentStatus } from './types';

export const PHASE_OPTIONS: Array<[CollaborationPhase, string]> = [
  ['lead', 'Contatto'],
  ['proposal', 'Proposta'],
  ['confirmed', 'Confermato'],
  ['production', 'Produzione'],
  ['approval', 'In approvazione'],
  ['scheduled', 'Programmato'],
  ['published', 'Pubblicato'],
  ['completed', 'Chiuso'],
  ['paused', 'In pausa'],
  ['lost', 'Non acquisito']
];

export const KIND_OPTIONS: Array<[CollaborationKind, string]> = [
  ['partnership', 'Partnership'],
  ['organic', 'Organico'],
  ['event', 'Evento'],
  ['giuntitrail', 'Giuntitrail']
];

export const PAYMENT_OPTIONS: Array<[PaymentStatus, string]> = [
  ['not_due', 'Non ancora dovuto'],
  ['to_invoice', 'Da fatturare'],
  ['invoiced', 'Fatturato'],
  ['overdue', 'Scaduto'],
  ['paid', 'Incassato']
];

export const CONTRACT_OPTIONS: Array<[ContractStatus, string]> = [
  ['not_needed', 'Non necessario'],
  ['draft', 'Bozza'],
  ['sent', 'Inviato'],
  ['signed', 'Firmato']
];

export const DELIVERABLE_OPTIONS: Array<[DeliverableStatus, string]> = [
  ['planned', 'Da iniziare'],
  ['in_progress', 'In lavorazione'],
  ['approval', 'In approvazione'],
  ['scheduled', 'Programmato'],
  ['published', 'Pubblicato']
];

export const IDEA_OPTIONS: Array<[IdeaStatus, string]> = [
  ['inbox', 'Inbox'],
  ['selected', 'Selezionata'],
  ['scheduled', 'Pianificata'],
  ['archived', 'Archiviata']
];

export const labelFor = <T extends string>(options: Array<[T, string]>, value: T) =>
  options.find(([key]) => key === value)?.[1] ?? value;
