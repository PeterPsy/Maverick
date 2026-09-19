import { FormEvent, useState } from 'react';
import { callBackend } from '../api';
import { LinkedRef, operationAliases, operationLabels } from '../domain/integrations';
import { Provider, Selection } from '../domain/vnext';

export function ProviderActionForm({ selected, providers, refs, refresh }: { selected: Selection; providers: Provider[]; refs: LinkedRef[]; refresh: () => void }) {
  const [kind, setKind] = useState('mail_draft');
  const [refId, setRefId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [body, setBody] = useState('');
  const configured = providers.some((p) => p.alias === operationAliases[kind] && p.configured);
  const relevant = refs.filter((r) => r.metadata.resolution_status === 'resolved' && (kind === 'transcription' ? r.provider_alias === 'files' && r.metadata.workspace_relative_path : r.provider_alias === 'tasks' && (kind !== 'task_status' || r.metadata.task_id)));
  async function prepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const form = new FormData(event.currentTarget);
    const params: Record<string, unknown> = Object.fromEntries(form);
    if (kind === 'mail_draft') params.attachment_ref_ids = form.getAll('attachment_ref_ids');
    try {
      if (kind === 'calendar_event') { params.startTime = new Date(String(params.startTime)).toISOString(); params.endTime = new Date(String(params.endTime)).toISOString(); params.attendees = String(params.attendees || '').split(',').map((s) => s.trim()).filter(Boolean); }
      await callBackend({ action: 'crm.integration_prepare', entity_type: selected.entity, entity_id: selected.record.id, kind, parameters: params });
      refresh();
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to prepare operation.'); }
    finally { setBusy(false); }
  }
  async function useBrief() {
    setError('');
    try { const result = await callBackend<{ brief: string }>({ action: 'crm.meeting_brief', entity_type: selected.entity, entity_id: selected.record.id }); setBody(result.brief); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to compose brief.'); }
  }
  return <details><summary>Prepare an app action</summary><label>Action<select aria-label="Action" value={kind} onChange={(e) => { setKind(e.target.value); setRefId(''); }}>{Object.entries(operationLabels).map(([id, title]) => <option key={id} value={id}>{title}</option>)}</select></label>
    {!configured ? <p className="crm-alert">Select the {operationAliases[kind]} provider in workspace Settings first.</p> : null}
    <form key={kind} onSubmit={(event) => void prepare(event)}>
      {kind === 'mail_draft' ? <><label>Reply to linked thread (optional)<select name="reply_ref_id"><option value="">New message</option>{refs.filter((r) => r.source_entity_type === 'email_thread' && r.metadata.resolution_status === 'resolved').map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label><label>Recipient email<input name="to" type="email" defaultValue={String(selected.record.email || '')} /></label><label>Mail connection ID (optional)<input name="connection_id" /></label><label>Subject<input name="subject" required maxLength={300} /></label><label>Linked Storage attachments (optional)<select name="attachment_ref_ids" multiple>{refs.filter((r) => r.provider_alias === 'files' && r.metadata.resolution_status === 'resolved' && r.metadata.workspace_relative_path).map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label></> : null}
      {kind === 'calendar_event' || kind === 'checklist_task' ? <label>Title<input name="title" required maxLength={300} /></label> : null}
      {kind === 'calendar_event' ? <><div className="vn-form-grid"><label>Starts (your local time)<input name="startTime" type="datetime-local" required /></label><label>Ends (your local time)<input name="endTime" type="datetime-local" required /></label></div><label>Attendees (comma-separated emails)<input name="attendees" defaultValue={String(selected.record.email || '')} /></label><label>Location<input name="location" /></label><p className="vn-hint">Creates a Maverick Calendar event. It does not promise external calendar invitations.</p></> : null}
      {['mail_draft', 'calendar_event', 'document'].includes(kind) ? <><label>{kind === 'document' ? 'Markdown document' : 'Content'}<textarea rows={6} name={kind === 'mail_draft' ? 'body_text' : kind === 'document' ? 'content' : 'description'} value={body} onChange={(e) => setBody(e.target.value)} required={kind !== 'calendar_event'} /></label><button type="button" onClick={() => void useBrief()}>Use CRM meeting brief</button></> : null}
      {['checklist_task', 'task_status', 'transcription'].includes(kind) ? <label>{kind === 'transcription' ? 'Linked Storage audio' : 'Linked Checklist record'}<select name="ref_id" required value={refId} onChange={(e) => setRefId(e.target.value)}><option value="">Select a verified link</option>{relevant.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label> : null}
      {kind === 'checklist_task' ? <label>Checklist section<select name="section_id" required>{relevant.find((r) => r.id === refId)?.metadata.sections?.map((section) => <option key={section.id} value={section.id}>{section.title || section.id}</option>)}</select></label> : null}
      {kind === 'task_status' ? <label>New status<select name="status">{['pending', 'in-progress', 'need-help', 'blocked', 'completed', 'failed'].map((s) => <option key={s}>{s}</option>)}</select></label> : null}
      {kind === 'transcription' ? <label>Language (optional)<input name="language" maxLength={20} placeholder="it" /></label> : null}
      <p className="vn-hint">Prepare → review → approve → execute. {kind === 'mail_draft' ? 'No email is sent here. Review and send the actual draft in Mail.' : kind === 'transcription' ? 'Speech processes the selected audio; the transcript becomes a separate reviewable note proposal.' : 'The provider remains the source of truth.'}</p>
      {error ? <p className="crm-alert" role="alert">{error}</p> : null}<button disabled={busy || !configured} className="vn-primary">{busy ? 'Preparing…' : 'Prepare proposal'}</button>
    </form></details>;
}
