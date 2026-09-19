import { FormEvent, useState } from 'react';
import { ArrowRight, Link2, Unlink } from 'lucide-react';
import { callBackend, CrmRecord } from '../api';
import { allEntities, label, Provider, Selection, useLiveCrm } from '../domain/vnext';
import { titleFor } from '../domain/routing';
import { RecordPicker } from './ExtensionComposer';

type GraphContext = { links: Array<{ id: string; relationship: string; record: CrmRecord }> };

export function RecordRelationships({ selected, select }: { selected: Selection; select?: (selection: Selection) => void }) {
  const [targetType, setTargetType] = useState('contact');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const context = useLiveCrm<GraphContext>({ action: 'crm.record_context', entity_type: selected.entity, id: selected.record.id });
  const providers = useLiveCrm<{ providers: Provider[] }>({ action: 'crm.integration_context' });
  async function submit(event: FormEvent<HTMLFormElement>, provider = false) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(''); setSaving(true);
    try {
      await callBackend(provider ? { action: 'crm.link_provider_record', crm_entity_type: selected.entity, crm_entity_id: selected.record.id, ...Object.fromEntries(form) }
        : { action: 'crm.link_records', source_type: selected.entity, source_id: selected.record.id, target_type: targetType, ...Object.fromEntries(form) });
      context.refresh();
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to link record.'); }
    finally { setSaving(false); }
  }
  async function unlink(id: string) {
    setSaving(true); setError('');
    try { await callBackend({ action: 'crm.unlink_records', id }); context.refresh(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to unlink.'); }
    finally { setSaving(false); }
  }
  return <section className="vn-surface vn-relationships"><h2><Link2 size={18} /> Relationships</h2>
    {error || context.error ? <p className="crm-alert" role="alert">{error || context.error}</p> : null}
    {context.data?.links.map((link) => <div className="vn-linked-row" key={link.id}><button disabled={!select} onClick={() => select?.({ entity: String(link.record.entity_type), record: link.record })}><span>{label(String(link.record.entity_type))} · {link.relationship}</span><strong>{titleFor(link.record)} <ArrowRight size={14} /></strong></button><button aria-label={`Unlink ${titleFor(link.record)}`} disabled={saving} onClick={() => void unlink(link.id)}><Unlink size={15} /></button></div>)}
    <details><summary>Connect a CRM record</summary><form onSubmit={(event) => void submit(event)}><label>Record type<select value={targetType} onChange={(event) => setTargetType(event.target.value)}>{allEntities.map((type) => <option key={type} value={type}>{label(type)}</option>)}</select></label><label>Record<RecordPicker key={targetType} entity={targetType} name="target_id" required /></label><label>Relationship<input name="relationship" defaultValue="related" required /></label><button disabled={saving} className="vn-primary">Link record</button></form></details>
    <details><summary>Connect a Maverick app record</summary><p className="vn-hint">Use the record identity supplied by the selected provider. This does not create, send or copy a remote record.</p><form onSubmit={(event) => void submit(event, true)}><label>Provider<select name="provider_alias" required><option value="">Select provider</option>{providers.data?.providers.filter((provider) => provider.configured).map((provider) => <option value={provider.alias} key={provider.alias}>{provider.alias} · {provider.selected_provider_app_ids[0]}</option>)}</select></label><label>Provider entity type<input name="source_entity_type" required placeholder="e.g. email_thread" /></label><label>Provider record ID<input name="source_entity_id" required /></label><label>Title<input name="title" /></label><button disabled={saving} className="vn-primary">Link provider record</button></form>{providers.error ? <p role="alert">{providers.error}</p> : null}</details>
  </section>;
}
