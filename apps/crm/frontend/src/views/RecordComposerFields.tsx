import { BootstrapPayload, CrmRecord } from '../api';
import { CreatableEntity } from '../domain/types';
import { AccountComposerFields, ContactComposerFields, DealComposerFields, LeadComposerFields } from './RecordComposerSalesFields';
import { NoteComposerFields, TaskComposerFields } from './RecordComposerWorkFields';

export function RecordComposerFields({ entity, record, data }: { entity: CreatableEntity; record: Partial<CrmRecord>; data: BootstrapPayload }) {
  if (entity === 'lead') {
    return <LeadComposerFields record={record} />;
  }
  if (entity === 'account') {
    return <AccountComposerFields record={record} />;
  }
  if (entity === 'contact') {
    return <ContactComposerFields record={record} data={data} />;
  }
  if (entity === 'deal') {
    return <DealComposerFields record={record} data={data} />;
  }
  if (entity === 'task') {
    return <TaskComposerFields record={record} data={data} />;
  }
  return <NoteComposerFields record={record} data={data} />;
}
