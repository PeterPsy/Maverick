import { BootstrapPayload, CrmRecord } from '../api';
import { EntityRecord } from './types';
import { recordKey, refKey } from './routing';

export type CrmViewModel = {
  leads: CrmRecord[];
  accounts: CrmRecord[];
  contacts: CrmRecord[];
  deals: CrmRecord[];
  activities: CrmRecord[];
  tasks: CrmRecord[];
  notes: CrmRecord[];
  all: EntityRecord[];
  isCustom: boolean;
  title: string;
};

export function buildCrmViewModel(data: BootstrapPayload): CrmViewModel {
  const viewFilter = data.view_state?.view_filter;
  const refs = new Set((viewFilter?.refs || []).map(refKey).filter(Boolean));
  const isCustom = viewFilter?.mode === 'custom' && refs.size > 0;
  const searchEntityType = viewFilter?.mode === 'search' && viewFilter.entity_type ? viewFilter.entity_type : 'all';
  const filterRecords = (entity: string, records: CrmRecord[]) => {
    const scopedRecords = searchEntityType !== 'all' && searchEntityType !== entity ? [] : records;
    return isCustom ? scopedRecords.filter((record) => refs.has(recordKey(entity, record))) : scopedRecords;
  };
  const leads = filterRecords('lead', data.leads);
  const accounts = filterRecords('account', data.accounts);
  const contacts = filterRecords('contact', data.contacts);
  const deals = filterRecords('deal', data.deals);
  const activities = filterRecords('activity', data.activities);
  const tasks = filterRecords('task', data.tasks);
  const notes = filterRecords('note', data.notes);
  const all: EntityRecord[] = [
    ...leads.map((record) => ({ entity: 'lead', record })),
    ...accounts.map((record) => ({ entity: 'account', record })),
    ...contacts.map((record) => ({ entity: 'contact', record })),
    ...deals.map((record) => ({ entity: 'deal', record })),
    ...activities.map((record) => ({ entity: 'activity', record })),
    ...tasks.map((record) => ({ entity: 'task', record })),
    ...notes.map((record) => ({ entity: 'note', record }))
  ];
  return {
    leads,
    accounts,
    contacts,
    deals,
    activities,
    tasks,
    notes,
    all,
    isCustom,
    title: viewFilter?.title || 'Custom view'
  };
}
