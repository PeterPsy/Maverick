import { useState } from 'react';
import { callBackend, CrmRecord, DuplicateGroup, WorkflowProposal, WorkflowProposalPreviewPayload } from '../../api';
import { Selection, useLiveCrm } from '../../domain/vnext';
import { titleFor } from '../../domain/routing';
import { ViewId } from '../../domain/types';
import { date, LoadState, PageHeading, Pager, Refresh, Segments, useWorkspaceView } from './WorkspacePrimitives';

export function QualityWorkspace({ query, select, navigate }: { query: string; select: (selection: Selection) => void; navigate: (view: ViewId) => void }) {
  const [entity, setEntity] = useState('contact');
  const result = useWorkspaceView('quality', query, { entity_type: entity });
  const duplicates = useLiveCrm<{ groups: DuplicateGroup[] }>({ action: 'crm.find_duplicates', limit: 100 });
  return <section className="product-page"><PageHeading eyebrow="RELATIONSHIP HEALTH" title="Data quality" description="Review missing information and exact duplicate candidates. Nothing is merged or enriched automatically."><Refresh run={() => { result.refresh(); duplicates.refresh(); }} /><button onClick={() => navigate('proposals')}>Review proposals</button></PageHeading><Segments label="Quality record type" value={entity} change={setEntity} choices={[[ 'contact', 'People' ], [ 'account', 'Companies' ], [ 'lead', 'Leads' ]]} />
    <section className="product-card"><header><h2>Missing {entity === 'account' ? 'website domain' : 'email'}</h2><small>{result.data?.total || 0} records</small></header><LoadState loading={result.loading} error={result.error} empty={!result.data?.items.length}>No missing fields in this view.</LoadState>{!result.loading && result.data?.items.map((record) => <button className="product-row" key={record.id} onClick={() => select({ entity, record })}><strong>{titleFor(record)}</strong><span>{String(record.quality_issue).replace(/_/g, ' ')} · Open record to review and edit</span></button>)}<Pager offset={result.offset} hasMore={!!result.data?.has_more} loading={result.loading} onChange={result.setOffset} /></section>
    <section className="product-card"><header><h2>Duplicate candidates</h2><button onClick={() => navigate('pipeline')}>Open merge review</button></header><p className="product-hint">Up to 100 exact-match groups, independently of the missing-field search. Check each identity before merging.</p><LoadState loading={duplicates.loading} error={duplicates.error} empty={!duplicates.data?.groups.length}>No exact duplicate candidates found.</LoadState>{duplicates.data?.groups.map((group, index) => <article className="product-duplicate" key={`${group.entity_type}:${group.field}:${index}`}><strong>{group.field}: {group.value}</strong><div className="vn-actions">{group.records.map((record) => <button key={record.id} onClick={() => select({ entity: group.entity_type, record })}>{titleFor(record)}</button>)}</div></article>)}</section>
  </section>;
}

export function ProposalsWorkspace({ query, select }: { query: string; select: (selection: Selection) => void }) {
  const [status, setStatus] = useState('active');
  const result = useLiveCrm<{ workflow_proposals: WorkflowProposal[] }>({ action: 'crm.list_workflow_proposals', status, limit: 200 });
  const [preview, setPreview] = useState<WorkflowProposalPreviewPayload | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const proposals = result.data?.workflow_proposals.filter((item) => item.title.toLowerCase().includes(query.toLowerCase())) || [];
  async function act(action: string, id: string) {
    setError(''); setBusy(true);
    try { const response = await callBackend<WorkflowProposalPreviewPayload>({ action, id }); if (action === 'crm.workflow_proposal_preview') setPreview(response); else { setPreview(null); result.refresh(); } }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to process proposal.'); }
    finally { setBusy(false); }
  }
  async function open(proposal: WorkflowProposal) {
    setError(''); setBusy(true);
    try { const response = await callBackend<{ record: CrmRecord }>({ action: 'crm.get_record', entity_type: proposal.entity_type, id: proposal.entity_id }); select({ entity: proposal.entity_type, record: response.record }); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to open proposal context.'); }
    finally { setBusy(false); }
  }
  return <section className="product-page"><PageHeading eyebrow="YOUR DECISION" title="Proposals" description="Review exact changes before approval. Approval and execution remain separate actions."><Refresh run={result.refresh} /></PageHeading><Segments label="Proposal status" value={status} change={(value) => { setStatus(value); setPreview(null); }} choices={[[ 'active', 'To review' ], [ 'applied', 'Applied' ], [ 'dismissed', 'Dismissed' ], [ 'rejected', 'Rejected' ]]} /><p className="product-hint">Latest 200 proposals in the selected status. Provider actions execute only from their connected CRM context.</p>
    <LoadState loading={result.loading} error={result.error || error} empty={!proposals.length}>No proposals in this view.</LoadState>
    {!result.loading && proposals.map((proposal) => <article className="product-card product-proposal" key={proposal.id}><header><div><small>{proposal.proposal_type?.replace(/_/g, ' ')}</small><h2>{proposal.title}</h2></div><span className="product-badge">{proposal.status}</span></header><small>{date(proposal.updated_at)} · {proposal.source || 'CRM'}</small><details><summary>Proposed content</summary><pre className="vn-provenance">{JSON.stringify(proposal.proposal, null, 2)}</pre></details>
      {preview?.workflow_proposal.id === proposal.id ? <div className="product-preview"><h3>Validated preview</h3><pre className="vn-provenance">{JSON.stringify(preview.preview, null, 2)}</pre></div> : null}
      <div className="vn-actions"><button disabled={busy} onClick={() => void open(proposal)}>Open context</button>{['pending', 'approved'].includes(proposal.status) ? <><button disabled={busy} onClick={() => void act('crm.workflow_proposal_preview', proposal.id)}>Preview changes</button>{proposal.status === 'pending' ? <button disabled={busy || preview?.workflow_proposal.id !== proposal.id || !preview.preview.can_approve} onClick={() => void act('crm.approve_workflow_proposal', proposal.id)}>Approve proposal</button> : proposal.proposal_type !== 'provider_operation' ? <button disabled={busy || preview?.workflow_proposal.id !== proposal.id || !preview.preview.can_apply} onClick={() => void act('crm.apply_workflow_proposal', proposal.id)}>Apply approved proposal</button> : null}<button disabled={busy} onClick={() => void act('crm.dismiss_workflow_proposal', proposal.id)}>Dismiss</button><button disabled={busy} onClick={() => void act('crm.reject_workflow_proposal', proposal.id)}>Reject</button></> : null}</div>
    </article>)}
  </section>;
}

export function TranscriptsWorkspace({ query, select }: { query: string; select: (selection: Selection) => void }) {
  const result = useWorkspaceView('transcripts', query);
  const [chosenId, setChosenId] = useState('');
  const [error, setError] = useState('');
  const chosen = result.data?.items.find((item) => item.id === chosenId) || result.data?.items[0];
  async function open(record: CrmRecord) {
    setError('');
    try { const response = await callBackend<{ record: CrmRecord }>({ action: 'crm.get_record', entity_type: record.entity_type, id: record.entity_id }); select({ entity: String(record.entity_type), record: response.record }); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to open transcript context.'); }
  }
  return <section className="product-page"><PageHeading eyebrow="MEETING MEMORY" title="Transcripts" description="Speech processing history and reviewable transcripts, linked to their CRM context."><Refresh run={result.refresh} /></PageHeading><p className="product-hint">To transcribe: open a CRM record, link verified Storage audio, then prepare “Transcribe linked audio” in Connected work. Speech output requires a separate note review.</p>
    <LoadState loading={result.loading} error={result.error || error} empty={!result.data?.items.length}>No transcription operations yet. No audio is processed automatically.</LoadState>
    {!result.loading && chosen ? <div className="product-transcript-grid"><div className="product-card">{result.data?.items.map((item) => <button className="product-row" key={item.id} aria-pressed={chosen.id === item.id} onClick={() => setChosenId(item.id)}><strong>{date(item.created_at)} · {item.status}</strong><small>{String(item.provider_app_id)} · {String(item.entity_type)}</small></button>)}</div><article className="product-card"><header><h2>Transcript</h2><span className="product-badge">{chosen.status}</span></header>{chosen.last_error ? <p className="crm-alert">{String(chosen.last_error)}</p> : null}<p className="product-brief-body">{String(chosen.text || 'No transcript available for this operation.')}</p><button onClick={() => void open(chosen)}>Open context & review note proposal</button></article></div> : null}
    <Pager offset={result.offset} hasMore={!!result.data?.has_more} loading={result.loading} onChange={result.setOffset} />
  </section>;
}
