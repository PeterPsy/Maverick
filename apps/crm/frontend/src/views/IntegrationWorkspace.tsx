import { useState } from 'react';
import { callBackend, WorkflowProposal } from '../api';
import { IntegrationOperation, LinkedRef, operationLabels, providerHref } from '../domain/integrations';
import { Provider, Selection, useLiveCrm } from '../domain/vnext';
import { ProviderBrowser } from './ProviderBrowser';
import { ProviderActionForm } from './ProviderActionForm';
import { MeetingOutcome } from './MeetingOutcome';
import { useProviderRefresh } from '../domain/integrations';

export function IntegrationWorkspace({ selected }: { selected: Selection }) {
  const request = { entity_type: selected.entity, entity_id: selected.record.id };
  const providers = useLiveCrm<{ providers: Provider[] }>({ action: 'crm.integration_context' });
  const context = useLiveCrm<{ external_refs: LinkedRef[] }>({ action: 'crm.record_context', entity_type: selected.entity, id: selected.record.id });
  const journal = useLiveCrm<{ operations: IntegrationOperation[]; proposals?: WorkflowProposal[] }>({ action: 'crm.integration_list', ...request });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const refs = context.data?.external_refs || [];
  useProviderRefresh(selected, refs);
  function refresh() { context.refresh(); journal.refresh(); providers.refresh(); }
  async function action(body: Record<string, unknown>) {
    setBusy(true); setError(''); setSuccess('');
    try { await callBackend(body); refresh(); setSuccess('Request processed. Check the recorded status below.'); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Integration failed.'); refresh(); }
    finally { setBusy(false); }
  }
  return <section className="vn-surface vn-integrations"><div className="vn-list-toolbar"><h2>Connected work</h2><button disabled={busy} onClick={() => void action({ action: 'crm.integration_refresh', ...request })}>Refresh linked records</button></div>
    {error || context.error || journal.error || providers.error ? <p role="alert" className="crm-alert">{error || context.error || journal.error || providers.error}</p> : null}{success ? <p role="status" className="vn-hint">{success}</p> : null}
    {refs.map((ref) => <div className="vn-linked-row" key={ref.id}><div><a href={providerHref(ref)} target="_top"><strong>{ref.title}</strong></a><p className="vn-hint">{ref.provider_alias || ref.source_app_id} · {ref.metadata.status || ref.metadata.resolution_status || 'Snapshot'}<br />Last verified: {ref.metadata.last_synced_at || 'Not yet verified'}</p>{ref.metadata.last_error ? <p className="crm-alert">{ref.metadata.last_error} Last good snapshot retained.</p> : null}</div></div>)}
    <ProviderBrowser selected={selected} providers={providers.data?.providers || []} refresh={refresh} />
    <ProviderActionForm selected={selected} providers={providers.data?.providers || []} refs={refs} refresh={refresh} />
    <MeetingOutcome selected={selected} refs={refs} refresh={refresh} />
    <h3>Proposals & execution history</h3>
    {journal.data?.operations?.filter((op) => !['refresh', 'resolve'].includes(op.kind) || op.status !== 'succeeded').map((op) => <article key={op.id} className="vn-operation"><strong>{operationLabels[op.kind] || op.kind} · {op.provider_app_id}</strong><p className="vn-hint">{op.status} {op.approval_status ? `· ${op.approval_status}` : ''}</p>
      <details><summary>Review exact request & result</summary><pre className="vn-provenance">{JSON.stringify({ request: op.request.body, result: op.result }, null, 2)}</pre></details>
      {op.last_error ? <p role="alert" className="crm-alert">{op.last_error}</p> : null}
      <div className="vn-actions">{op.status === 'prepared' && op.approval_status === 'pending' ? <><button disabled={busy} onClick={() => void action({ action: 'crm.approve_workflow_proposal', id: op.proposal_id })}>Approve proposal</button><button disabled={busy} onClick={() => void action({ action: 'crm.dismiss_workflow_proposal', id: op.proposal_id })}>Dismiss</button></> : null}
      {op.status === 'prepared' && op.approval_status === 'approved' ? <button disabled={busy} onClick={() => void action({ action: 'crm.integration_run', id: op.id })}>Execute approved action</button> : null}
      {['failed', 'uncertain', 'running'].includes(op.status) && ['calendar_event', 'search', 'resolve', 'refresh', 'reconcile'].includes(op.kind) ? <button disabled={busy} onClick={() => void action({ action: 'crm.integration_retry', id: op.id })}>Retry safely</button> : null}
      {op.result.external_ref ? <a href={providerHref(op.result.external_ref)} target="_top">Open result in provider</a> : null}</div>
      {['uncertain', 'running'].includes(op.status) && ['mail_draft', 'calendar_event', 'document', 'checklist_task'].includes(op.kind) ? <details><summary>Reconcile an existing provider result (do not repeat write)</summary><form onSubmit={(event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); void action({ action: 'crm.integration_reconcile', ...request, original_operation_id: op.id, provider_alias: op.provider_alias === 'file-write' ? 'files' : op.provider_alias, source_entity_type: op.kind === 'mail_draft' ? 'mail_draft' : op.kind === 'calendar_event' ? 'event' : op.kind === 'document' ? 'file' : 'checklist', ...data }); }}><label>Existing provider record ID<input name="source_entity_id" required /></label>{op.kind === 'checklist_task' ? <label>Existing task ID<input name="task_id" required /></label> : null}<button disabled={busy}>Verify and adopt result</button></form></details> : null}
    </article>)}
    {journal.data?.proposals?.filter((p) => p.proposal_type !== 'provider_operation' && ['pending', 'approved'].includes(p.status)).map((proposal) => <article key={proposal.id} className="vn-operation"><strong>{proposal.title}</strong><details><summary>Review proposed content</summary><pre className="vn-provenance">{JSON.stringify(proposal.proposal, null, 2)}</pre></details><button disabled={busy} onClick={() => void action({ action: proposal.status === 'pending' ? 'crm.approve_workflow_proposal' : 'crm.apply_workflow_proposal', id: proposal.id })}>{proposal.status === 'pending' ? 'Approve proposal' : 'Apply approved proposal'}</button><button disabled={busy} onClick={() => void action({ action: 'crm.dismiss_workflow_proposal', id: proposal.id })}>Dismiss</button></article>)}
  </section>;
}
