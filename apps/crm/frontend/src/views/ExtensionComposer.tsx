import { FormEvent, useState } from 'react';
import { X } from 'lucide-react';
import { callBackend, CrmRecord } from '../api';
import { allEntities, ExtensionSchema, label, useLiveCrm } from '../domain/vnext';

export function RecordPicker({ entity, name, defaultValue = '', required = false }: { entity: string; name: string; defaultValue?: string; required?: boolean }) {
  const [query, setQuery] = useState('');
  const [value, setValue] = useState(defaultValue);
  const result = useLiveCrm<{ results: Array<{ entity_id?: string; title?: string; record?: CrmRecord }> }>({ action: 'crm.search', entity_type: entity, query, limit: 50 });
  const choices = (result.data?.results || []).map((item) => ({ id: item.entity_id || item.record?.id || '', title: item.title || item.record?.name || item.record?.display_name || item.record?.title || item.record?.id || '' }));
  return <span className="vn-picker">
    <input aria-label={`Search ${label(entity)}`} value={query} placeholder={`Search ${label(entity).toLowerCase()}…`} onChange={(event) => setQuery(event.target.value)} />
    <select name={name} value={value} required={required} onChange={(event) => setValue(event.target.value)}>
      <option value="">Select a record</option>
      {value && !choices.some((item) => item.id === value) ? <option value={value}>{value}</option> : null}
      {choices.map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}
    </select>
    {result.error ? <small role="alert">{result.error}</small> : null}
  </span>;
}

export function ExtensionComposer({ entity, record, defaults = {}, onClose, onSaved }: { entity: string; record?: CrmRecord; defaults?: Record<string, unknown>; onClose: () => void; onSaved: (record: CrmRecord) => void }) {
  const schema = useLiveCrm<ExtensionSchema>({ action: 'crm.extension_schema' });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [recipientType, setRecipientType] = useState(String(record?.record_type || 'contact'));
  const spec = schema.data?.entities[entity];
  const initial: Record<string, unknown> = { ...spec?.defaults, ...defaults, ...record };
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!spec) return;
    const form = new FormData(event.currentTarget);
    setError(''); setSaving(true);
    try {
      const values: Record<string, unknown> = Object.fromEntries(form);
      for (const [key, kind] of Object.entries(spec.fields)) {
        if (kind === 'integer') values[key] = Number(values[key] || 0);
        if (kind === 'json') values[key] = JSON.parse(String(values[key] || '{}'));
      }
      const result = await callBackend<{ record: CrmRecord }>({ action: record ? 'crm.update_extension_record' : 'crm.create_extension_record', entity_type: entity, ...(record ? { id: record.id } : {}), ...values });
      onSaved(result.record);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to save record.'); }
    finally { setSaving(false); }
  }
  return <div className="vn-modal-backdrop"><section className="vn-modal" role="dialog" aria-modal="true" aria-labelledby="vn-composer-title">
    <header><h2 id="vn-composer-title">{record ? 'Edit' : 'New'} {label(entity).toLowerCase()}</h2><button aria-label="Close editor" onClick={onClose} disabled={saving}><X size={18} /></button></header>
    {error || schema.error ? <p className="crm-alert" role="alert">{error || schema.error}</p> : null}
    {!spec ? <p>Loading fields…</p> : <form onSubmit={submit}>
      <label>Title<input name="title" required autoFocus defaultValue={String(initial.title || '')} /></label>
      <div className="vn-form-grid">{Object.entries(spec.fields).map(([field, kind]) => <label key={field}>{label(field)}
        {kind.startsWith('ref:') ? <RecordPicker entity={kind.slice(4)} name={field} defaultValue={String(initial[field] || '')} required={spec.required?.includes(field)} />
          : field === 'record_type' ? <select name={field} value={recipientType} onChange={(event) => setRecipientType(event.target.value)}>{allEntities.map((type) => <option key={type} value={type}>{label(type)}</option>)}</select>
          : field === 'record_id' ? <RecordPicker key={recipientType} entity={recipientType} name={field} defaultValue={String(initial[field] || '')} required />
          : kind === 'json' ? <textarea name={field} rows={4} defaultValue={JSON.stringify(initial[field] || {}, null, 2)} spellCheck={false} />
          : field === 'status' && entity === 'campaign' ? <select name={field} defaultValue={String(initial[field] || 'draft')}>{['draft', 'ready', 'paused', 'completed'].map((status) => <option key={status}>{status}</option>)}</select>
          : <input name={field} type={kind === 'integer' ? 'number' : 'text'} step={kind === 'integer' ? 1 : undefined} required={spec.required?.includes(field)} placeholder={kind === 'date' ? 'YYYY-MM-DD or ISO timestamp' : ''} defaultValue={String(initial[field] ?? '')} />}
      </label>)}</div>
      <label>Notes / content<textarea name="body" rows={5} defaultValue={String(initial.body || '')} /></label>
      <label>Owner<input name="owner_id" defaultValue={String(initial.owner_id || '')} /></label>
      {entity.startsWith('campaign') ? <p className="vn-hint">Planning only. Saving does not send messages or schedule deliveries.</p> : null}
      <footer><button type="button" onClick={onClose} disabled={saving}>Cancel</button><button className="vn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save record'}</button></footer>
    </form>}
  </section></div>;
}
