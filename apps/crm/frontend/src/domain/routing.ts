import { CrmRecord, CrmViewRef } from '../api';
import { CreatableEntity, PendingSelection, RecordEntityFilter, ViewId } from './types';

export const viewIds: ViewId[] = ['records', 'pipeline', 'reports', 'import'];
export const recordEntityFilters: RecordEntityFilter[] = ['all', 'lead', 'account', 'contact', 'deal'];
export const creatableEntities: CreatableEntity[] = ['lead', 'account', 'contact', 'deal', 'task', 'note'];

export const createActions: Record<CreatableEntity, string> = {
  lead: 'crm.create_lead',
  account: 'crm.create_account',
  contact: 'crm.create_contact',
  deal: 'crm.create_deal',
  task: 'crm.create_task',
  note: 'crm.create_note'
};

export const updateActions: Record<CreatableEntity, string> = {
  lead: 'crm.update_lead',
  account: 'crm.update_account',
  contact: 'crm.update_contact',
  deal: 'crm.update_deal',
  task: 'crm.update_task',
  note: 'crm.update_note'
};

export function titleFor(record: CrmRecord) {
  return record.name || record.display_name || record.subject || record.title || String(record.body || '').slice(0, 48) || record.id;
}

export function viewFromAppPage(appPage: string): { view: ViewId; selection: PendingSelection; entityFilter: RecordEntityFilter } {
  const [segment, recordId] = appPage.split('/').filter(Boolean);
  const route = segment || 'records';
  const legacyEntityByRoute: Record<string, RecordEntityFilter> = {
    leads: 'lead',
    accounts: 'account',
    contacts: 'contact',
    deals: 'deal'
  };
  if (legacyEntityByRoute[route]) {
    const entityFilter = legacyEntityByRoute[route];
    return { view: 'records', entityFilter, selection: recordId ? { entity: entityFilter, id: recordId } : null };
  }
  if (route === 'tasks' || route === 'notes' || route === 'activities') {
    const entity = route === 'activities' ? 'activity' : route.replace(/s$/, '');
    return { view: 'pipeline', entityFilter: 'all', selection: recordId ? { entity, id: recordId } : null };
  }
  if (route === 'operations') {
    return { view: 'pipeline', entityFilter: 'all', selection: null };
  }
  const view = viewIds.includes(route as ViewId) ? (route as ViewId) : 'records';
  return { view, entityFilter: 'all', selection: null };
}

export function money(record: Partial<CrmRecord>) {
  const value = Number(record.value || 0);
  if (!value) return '';
  return `${record.currency || 'EUR'} ${value.toLocaleString()}`;
}

export function recordKey(entity: string, record: CrmRecord) {
  return `${entity}:${record.id}`;
}

export function fieldLabel(key: string) {
  return key.replace(/_/g, ' ');
}

export function refKey(ref: CrmViewRef) {
  const entityType = String(ref.entity_type || '');
  const rawId = String(ref.entity_id || ref.id || '');
  const id = rawId.includes(':') ? rawId.split(':').slice(1).join(':') : rawId;
  return entityType && id ? `${entityType}:${id}` : '';
}

export function entityFilterForEntity(entityType: string): RecordEntityFilter {
  return recordEntityFilters.includes(entityType as RecordEntityFilter) ? (entityType as RecordEntityFilter) : 'all';
}

export function viewForEntity(entityType: string): ViewId {
  if (['lead', 'account', 'contact', 'deal'].includes(entityType)) return 'records';
  if (['task', 'note', 'activity'].includes(entityType)) return 'pipeline';
  return 'records';
}

export function isCreatableEntity(value: unknown): value is CreatableEntity {
  return typeof value === 'string' && creatableEntities.includes(value as CreatableEntity);
}

export function entityLabel(entity: string) {
  const labels: Record<string, string> = {
    lead: 'Lead',
    account: 'Account',
    contact: 'Contact',
    deal: 'Deal',
    activity: 'Activity',
    task: 'Task',
    note: 'Note'
  };
  return labels[entity] || entity;
}

export function parseColumnMapping(value: FormDataEntryValue | null) {
  if (typeof value !== 'string' || !value.trim()) return {};
  return Object.fromEntries(
    value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [source, target] = line.split('=').map((part) => part.trim());
        return [source, target || source];
      })
  );
}
