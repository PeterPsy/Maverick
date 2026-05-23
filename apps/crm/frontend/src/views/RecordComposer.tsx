import { FormEvent, ReactNode } from 'react';
import { Building2, CheckSquare, Contact, Handshake, StickyNote, UserPlus, X } from 'lucide-react';
import { BootstrapPayload, CrmRecord } from '../api';
import { ComposerState, CreatableEntity } from '../domain/types';
import { entityLabel, titleFor } from '../domain/routing';

const createTargets = [
  { label: 'Lead', entity: 'lead', icon: UserPlus },
  { label: 'Account', entity: 'account', icon: Building2 },
  { label: 'Contact', entity: 'contact', icon: Contact },
  { label: 'Deal', entity: 'deal', icon: Handshake },
  { label: 'Task', entity: 'task', icon: CheckSquare },
  { label: 'Note', entity: 'note', icon: StickyNote }
] satisfies Array<{ label: string; entity: CreatableEntity; icon: typeof Building2 }>;

function textValue(record: Partial<CrmRecord>, key: string, fallback = '') {
  const value = record[key];
  return value === null || value === undefined ? fallback : String(value);
}

function numericValue(record: Partial<CrmRecord>, key: string, fallback = '') {
  const value = record[key];
  return typeof value === 'number' || typeof value === 'string' ? String(value) : fallback;
}

function SelectField({ label, name, defaultValue, children }: { label: string; name: string; defaultValue?: string; children: ReactNode }) {
  return (
    <label>
      {label}
      <select name={name} defaultValue={defaultValue || ''}>
        {children}
      </select>
    </label>
  );
}

function RelatedRecordOptions({ records }: { records: CrmRecord[] }) {
  return (
    <>
      <option value="">None</option>
      {records.map((record) => (
        <option key={record.id} value={record.id}>
          {titleFor(record)}
        </option>
      ))}
    </>
  );
}

function appendText(form: FormData, payload: Record<string, unknown>, key: string) {
  const value = form.get(key);
  payload[key] = typeof value === 'string' ? value.trim() : '';
}

function appendNumber(form: FormData, payload: Record<string, unknown>, key: string) {
  const value = form.get(key);
  const text = typeof value === 'string' ? value.trim() : '';
  payload[key] = text ? Number(text) : 0;
}

export function CreateChooserModal({ onClose, onChoose }: { onClose: () => void; onChoose: (entity: CreatableEntity) => void }) {
  return (
    <div className="crm-detail-overlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="crm-detail-dialog crm-create-chooser-dialog" role="dialog" aria-modal="true" aria-labelledby="crm-create-chooser-title">
        <header className="detail-header">
          <div>
            <small>create</small>
            <h2 id="crm-create-chooser-title">Add CRM record</h2>
          </div>
          <button className="detail-close" type="button" onClick={onClose} aria-label="Close create menu">
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="create-chooser-list">
          {createTargets.map((target) => {
            const Icon = target.icon;
            return (
              <button key={target.entity} type="button" onClick={() => onChoose(target.entity)}>
                <Icon size={18} aria-hidden="true" />
                <span>{target.label}</span>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}

export function RecordComposerModal({
  state,
  data,
  isSaving,
  onClose,
  onSubmit
}: {
  state: Exclude<ComposerState, null>;
  data: BootstrapPayload;
  isSaving: boolean;
  onClose: () => void;
  onSubmit: (values: Record<string, unknown>) => void;
}) {
  const record = state.mode === 'edit' ? state.record : {};
  const title = `${state.mode === 'create' ? 'Add' : 'Edit'} ${entityLabel(state.entity)}`;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const values: Record<string, unknown> = {};
    if (state.entity === 'lead') {
      ['display_name', 'first_name', 'last_name', 'email', 'phone', 'company', 'domain', 'source', 'status', 'owner_id', 'summary'].forEach((key) => appendText(form, values, key));
    } else if (state.entity === 'account') {
      ['name', 'domain', 'industry', 'status', 'owner_id', 'summary'].forEach((key) => appendText(form, values, key));
    } else if (state.entity === 'contact') {
      ['display_name', 'first_name', 'last_name', 'email', 'phone', 'role', 'account_id', 'owner_id', 'summary'].forEach((key) => appendText(form, values, key));
    } else if (state.entity === 'deal') {
      ['name', 'account_id', 'contact_id', 'stage_id', 'currency', 'close_date', 'owner_id', 'summary'].forEach((key) => appendText(form, values, key));
      appendNumber(form, values, 'value');
      appendNumber(form, values, 'probability');
    } else if (state.entity === 'task') {
      ['title', 'status', 'priority', 'due_at', 'account_id', 'contact_id', 'deal_id', 'owner_id', 'body'].forEach((key) => appendText(form, values, key));
    } else {
      ['body', 'account_id', 'contact_id', 'deal_id', 'owner_id'].forEach((key) => appendText(form, values, key));
    }
    onSubmit(values);
  }

  return (
    <div className="crm-detail-overlay" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="crm-detail-dialog crm-composer-dialog" role="dialog" aria-modal="true" aria-labelledby="crm-composer-title">
        <header className="detail-header">
          <div>
            <small>{state.mode}</small>
            <h2 id="crm-composer-title">{title}</h2>
          </div>
          <button className="detail-close" type="button" onClick={onClose} aria-label="Close composer">
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <form className="composer-form" onSubmit={handleSubmit}>
          {state.entity === 'lead' ? (
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
          ) : null}

          {state.entity === 'account' ? (
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
          ) : null}

          {state.entity === 'contact' ? (
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
          ) : null}

          {state.entity === 'deal' ? (
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
          ) : null}

          {state.entity === 'task' ? (
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
          ) : null}

          {state.entity === 'note' ? (
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
          ) : null}

          <div className="composer-actions">
            <button type="button" onClick={onClose}>Cancel</button>
            <button type="submit" disabled={isSaving}>{isSaving ? 'Saving...' : 'Save'}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
