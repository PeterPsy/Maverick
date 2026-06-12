import { BootstrapPayload, CrmRecord } from '../api';
import { RelatedRecordOptions, SelectField, textValue } from './RecordComposerControls';

export function TaskComposerFields({ record, data }: { record: Partial<CrmRecord>; data: BootstrapPayload }) {
  return (
    <div className="composer-grid">
      <label>
        Title
        <input name="title" required defaultValue={textValue(record, 'title')} />
      </label>
      <SelectField label="Status" name="status" defaultValue={textValue(record, 'status', 'open')}>
        <option value="open">Open</option>
        <option value="done">Done</option>
        <option value="blocked">Blocked</option>
      </SelectField>
      <SelectField label="Priority" name="priority" defaultValue={textValue(record, 'priority', 'normal')}>
        <option value="low">Low</option>
        <option value="normal">Normal</option>
        <option value="high">High</option>
      </SelectField>
      <label>
        Due date
        <input name="due_at" type="date" defaultValue={textValue(record, 'due_at')} />
      </label>
      <SelectField label="Account" name="account_id" defaultValue={textValue(record, 'account_id')}>
        <RelatedRecordOptions records={data.accounts} />
      </SelectField>
      <SelectField label="Contact" name="contact_id" defaultValue={textValue(record, 'contact_id')}>
        <RelatedRecordOptions records={data.contacts} />
      </SelectField>
      <SelectField label="Deal" name="deal_id" defaultValue={textValue(record, 'deal_id')}>
        <RelatedRecordOptions records={data.deals} />
      </SelectField>
      <label>
        Owner
        <input name="owner_id" defaultValue={textValue(record, 'owner_id')} />
      </label>
      <label className="span-2">
        Notes
        <textarea name="body" rows={4} defaultValue={textValue(record, 'body')} />
      </label>
    </div>
  );
}

export function NoteComposerFields({ record, data }: { record: Partial<CrmRecord>; data: BootstrapPayload }) {
  return (
    <div className="composer-grid">
      <label className="span-2">
        Note
        <textarea name="body" required rows={7} defaultValue={textValue(record, 'body')} />
      </label>
      <SelectField label="Account" name="account_id" defaultValue={textValue(record, 'account_id')}>
        <RelatedRecordOptions records={data.accounts} />
      </SelectField>
      <SelectField label="Contact" name="contact_id" defaultValue={textValue(record, 'contact_id')}>
        <RelatedRecordOptions records={data.contacts} />
      </SelectField>
      <SelectField label="Deal" name="deal_id" defaultValue={textValue(record, 'deal_id')}>
        <RelatedRecordOptions records={data.deals} />
      </SelectField>
      <label>
        Owner
        <input name="owner_id" defaultValue={textValue(record, 'owner_id')} />
      </label>
    </div>
  );
}
