import { FormEvent } from 'react';
import { Building2, CheckSquare, Contact, Handshake, StickyNote, UserPlus, X } from 'lucide-react';
import { BootstrapPayload } from '../api';
import { ComposerState, CreatableEntity } from '../domain/types';
import { entityLabel } from '../domain/routing';
import { RecordComposerFields } from './RecordComposerFields';

const createTargets = [
  { label: 'Lead', entity: 'lead', icon: UserPlus },
  { label: 'Account', entity: 'account', icon: Building2 },
  { label: 'Contact', entity: 'contact', icon: Contact },
  { label: 'Deal', entity: 'deal', icon: Handshake },
  { label: 'Task', entity: 'task', icon: CheckSquare },
  { label: 'Note', entity: 'note', icon: StickyNote }
] satisfies Array<{ label: string; entity: CreatableEntity; icon: typeof Building2 }>;

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
          <RecordComposerFields entity={state.entity} record={record} data={data} />

          <div className="composer-actions">
            <button type="button" onClick={onClose}>Cancel</button>
            <button type="submit" disabled={isSaving}>{isSaving ? 'Saving...' : 'Save'}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
