import { useState } from 'react';
import { callBackend, CrmRecord } from '../../api';

export function ThreadActions({ record, saved }: { record: CrmRecord; saved: (record: CrmRecord) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function move(status: string) {
    setBusy(true); setError('');
    try { const result = await callBackend<{ record: CrmRecord }>({ action: 'crm.update_extension_record', entity_type: 'conversation_thread', id: record.id, status }); saved(result.record); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to change thread state.'); }
    finally { setBusy(false); }
  }
  return <section className="product-thread-actions"><div className="vn-actions" role="group" aria-label="Conversation state">{[['open', 'To reply'], ['waiting', 'Waiting'], ['completed', 'Completed']].map(([status, title]) => <button key={status} disabled={busy || record.status === status} aria-pressed={record.status === status} onClick={() => void move(status)}>{title}</button>)}</div>{error ? <p role="alert" className="crm-alert">{error}</p> : null}</section>;
}
