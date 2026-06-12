import { BootstrapPayload, CrmRecord } from '../api';
import { numericValue, RelatedRecordOptions, SelectField, textValue } from './RecordComposerControls';

export function LeadComposerFields({ record }: { record: Partial<CrmRecord> }) {
  return (
    <div className="composer-grid">
      <label>
        Display name
        <input name="display_name" required defaultValue={textValue(record, 'display_name')} />
      </label>
      <label>
        Email
        <input name="email" type="email" defaultValue={textValue(record, 'email')} />
      </label>
      <label>
        Company
        <input name="company" defaultValue={textValue(record, 'company')} />
      </label>
      <label>
        Domain
        <input name="domain" defaultValue={textValue(record, 'domain')} />
      </label>
      <label>
        First name
        <input name="first_name" defaultValue={textValue(record, 'first_name')} />
      </label>
      <label>
        Last name
        <input name="last_name" defaultValue={textValue(record, 'last_name')} />
      </label>
      <SelectField label="Status" name="status" defaultValue={textValue(record, 'status', 'new')}>
        <option value="new">New</option>
        <option value="qualified">Qualified</option>
        <option value="nurture">Nurture</option>
        <option value="converted">Converted</option>
        <option value="disqualified">Disqualified</option>
      </SelectField>
      <label>
        Source
        <input name="source" defaultValue={textValue(record, 'source')} />
      </label>
      <label>
        Owner
        <input name="owner_id" defaultValue={textValue(record, 'owner_id')} />
      </label>
      <label>
        Phone
        <input name="phone" defaultValue={textValue(record, 'phone')} />
      </label>
      <label className="span-2">
        Summary
        <textarea name="summary" rows={4} defaultValue={textValue(record, 'summary')} />
      </label>
    </div>
  );
}

export function AccountComposerFields({ record }: { record: Partial<CrmRecord> }) {
  return (
    <div className="composer-grid">
      <label>
        Name
        <input name="name" required defaultValue={textValue(record, 'name')} />
      </label>
      <label>
        Domain
        <input name="domain" defaultValue={textValue(record, 'domain')} />
      </label>
      <label>
        Industry
        <input name="industry" defaultValue={textValue(record, 'industry')} />
      </label>
      <SelectField label="Status" name="status" defaultValue={textValue(record, 'status', 'prospect')}>
        <option value="prospect">Prospect</option>
        <option value="customer">Customer</option>
        <option value="partner">Partner</option>
        <option value="inactive">Inactive</option>
      </SelectField>
      <label>
        Owner
        <input name="owner_id" defaultValue={textValue(record, 'owner_id')} />
      </label>
      <label className="span-2">
        Summary
        <textarea name="summary" rows={4} defaultValue={textValue(record, 'summary')} />
      </label>
    </div>
  );
}

export function ContactComposerFields({ record, data }: { record: Partial<CrmRecord>; data: BootstrapPayload }) {
  return (
    <div className="composer-grid">
      <label>
        Display name
        <input name="display_name" required defaultValue={textValue(record, 'display_name')} />
      </label>
      <label>
        Email
        <input name="email" type="email" defaultValue={textValue(record, 'email')} />
      </label>
      <label>
        First name
        <input name="first_name" defaultValue={textValue(record, 'first_name')} />
      </label>
      <label>
        Last name
        <input name="last_name" defaultValue={textValue(record, 'last_name')} />
      </label>
      <SelectField label="Account" name="account_id" defaultValue={textValue(record, 'account_id')}>
        <RelatedRecordOptions records={data.accounts} />
      </SelectField>
      <label>
        Phone
        <input name="phone" defaultValue={textValue(record, 'phone')} />
      </label>
      <label>
        Role
        <input name="role" defaultValue={textValue(record, 'role')} />
      </label>
      <label>
        Owner
        <input name="owner_id" defaultValue={textValue(record, 'owner_id')} />
      </label>
      <label className="span-2">
        Summary
        <textarea name="summary" rows={4} defaultValue={textValue(record, 'summary')} />
      </label>
    </div>
  );
}

export function DealComposerFields({ record, data }: { record: Partial<CrmRecord>; data: BootstrapPayload }) {
  return (
    <div className="composer-grid">
      <label>
        Name
        <input name="name" required defaultValue={textValue(record, 'name')} />
      </label>
      <SelectField label="Stage" name="stage_id" defaultValue={textValue(record, 'stage_id', 'lead')}>
        {data.pipeline_stages.map((stage) => (
          <option key={stage.id} value={stage.id}>
            {stage.name}
          </option>
        ))}
      </SelectField>
      <SelectField label="Account" name="account_id" defaultValue={textValue(record, 'account_id')}>
        <RelatedRecordOptions records={data.accounts} />
      </SelectField>
      <SelectField label="Contact" name="contact_id" defaultValue={textValue(record, 'contact_id')}>
        <RelatedRecordOptions records={data.contacts} />
      </SelectField>
      <label>
        Value
        <input name="value" type="number" min="0" step="0.01" defaultValue={numericValue(record, 'value', '0')} />
      </label>
      <label>
        Currency
        <input name="currency" defaultValue={textValue(record, 'currency', 'EUR')} />
      </label>
      <label>
        Probability
        <input name="probability" type="number" min="0" max="1" step="0.01" defaultValue={numericValue(record, 'probability', '0')} />
      </label>
      <label>
        Close date
        <input name="close_date" type="date" defaultValue={textValue(record, 'close_date')} />
      </label>
      <label>
        Owner
        <input name="owner_id" defaultValue={textValue(record, 'owner_id')} />
      </label>
      <label className="span-2">
        Summary
        <textarea name="summary" rows={4} defaultValue={textValue(record, 'summary')} />
      </label>
    </div>
  );
}
