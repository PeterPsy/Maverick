import { FormEvent, useRef, useState } from 'react';
import { callBackend } from '../api';
import { Selection } from '../domain/vnext';
import { LinkedRef } from '../domain/integrations';

export function MeetingOutcome({ selected, refs, refresh }: { selected: Selection; refs: LinkedRef[]; refresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [brief, setBrief] = useState('');
  const key = useRef(crypto.randomUUID());
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const element = event.currentTarget; const form = new FormData(element); setBusy(true); setError('');
    try {
      await callBackend({ action: 'crm.meeting_outcome', entity_type: selected.entity, entity_id: selected.record.id, idempotency_key: key.current, summary: form.get('summary'), ref_id: form.get('ref_id'), followups: String(form.get('followups') || '').split('\n').filter((s) => s.trim()).map((title) => ({ title: title.trim() })) });
      key.current = crypto.randomUUID(); element.reset(); refresh();
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to record outcome.'); }
    finally { setBusy(false); }
  }
  async function loadBrief() {
    try { const result = await callBackend<{ brief: string }>({ action: 'crm.meeting_brief', entity_type: selected.entity, entity_id: selected.record.id }); setBrief(result.brief); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to load brief.'); }
  }
  return <details><summary>Meeting brief & outcome</summary><button onClick={() => void loadBrief()}>Read meeting brief</button>{brief ? <pre className="vn-provenance">{brief}</pre> : null}
    <form onSubmit={(event) => void submit(event)}><label>Linked meeting (optional)<select name="ref_id"><option value="">General meeting note</option>{refs.filter((r) => r.provider_alias === 'calendar').map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label><label>Outcome and decisions<textarea name="summary" required rows={5} /></label><label>Proposed follow-ups (one per line)<textarea name="followups" rows={3} /></label><p className="vn-hint">Records the outcome now. Follow-up tasks remain proposals until approved and applied.</p><button disabled={busy}>Record outcome</button></form>{error ? <p role="alert" className="crm-alert">{error}</p> : null}
  </details>;
}
