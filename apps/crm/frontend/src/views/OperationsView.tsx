import { AlertTriangle, Ban, Check, ClipboardList, Eye, GitMerge, Play, Search, Sparkles, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  BootstrapPayload,
  CrmRecord,
  DuplicateGroup,
  OperationsFeedItem,
  OperationsFeedPayload,
  WorkflowProposal,
  WorkflowProposalPreview,
  WorkflowProposalPreviewPayload,
  callBackend
} from '../api';
import { AuditEvent, OperationsFilters } from '../domain/types';
import { entityLabel, titleFor } from '../domain/routing';

type WorkflowProposalAction = 'approve' | 'apply' | 'dismiss' | 'reject';
type OperationsFeedSectionKey = 'to_do' | 'to_approve' | 'done' | 'discarded' | 'audit';

type PipelineOperationsDeckProps = {
  data: BootstrapPayload;
  filters: OperationsFilters;
  select: (value: { entity: string; record: CrmRecord }) => void;
  onWorkflowProposalAction: (id: string, action: WorkflowProposalAction) => Promise<boolean> | boolean;
  onWorkflowProposalPreview: (id: string) => Promise<WorkflowProposalPreviewPayload>;
  onDuplicateMerge?: () => Promise<void> | void;
};

type ProposalCard = {
  key: string;
  proposalId: string;
  title: string;
  status: WorkflowProposal['status'] | string;
  entityType: string;
  entityId: string;
  record?: CrmRecord;
  actionLabel: string;
  source: string;
  reason: string;
  evidence: string[];
  updatedAt?: string;
  proposal?: WorkflowProposal;
};

type ProposalReviewState = {
  card: ProposalCard;
  preview?: WorkflowProposalPreview;
  isLoading: boolean;
  error: string;
};

type DuplicateReviewState = {
  group: DuplicateGroup;
  targetId: string;
  sourceIds: string[];
  isMerging: boolean;
  error: string;
};

type AuditCard = {
  key: string;
  title: string;
  entityType: string;
  entityId: string;
  record?: CrmRecord;
  source: string;
  reason: string;
  createdAt?: string;
};

type ToDoCard = {
  key: string;
  kind: string;
  title: string;
  status: string;
  entityType: string;
  entityId: string;
  record?: CrmRecord;
  source: string;
  reason: string;
  priority?: string;
  score?: number;
  dueAt?: string;
  updatedAt?: string;
};

export function PipelineOperationsDeck({ data, filters, select, onWorkflowProposalAction, onWorkflowProposalPreview, onDuplicateMerge }: PipelineOperationsDeckProps) {
  const [operationsFeed, setOperationsFeed] = useState<OperationsFeedPayload | null>(null);
  const [allWorkflowProposals, setAllWorkflowProposals] = useState<WorkflowProposal[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [isLoadingOperations, setIsLoadingOperations] = useState(false);
  const [pendingProposalAction, setPendingProposalAction] = useState('');
  const [proposalReview, setProposalReview] = useState<ProposalReviewState | null>(null);
  const [duplicateReview, setDuplicateReview] = useState<DuplicateReviewState | null>(null);
  const [resolvedDuplicateKeys, setResolvedDuplicateKeys] = useState<Set<string>>(new Set());
  const [duplicateMergeNotice, setDuplicateMergeNotice] = useState('');
  const feedFilters = useMemo(() => operationsFeedFilters(filters), [filters]);
  const dataSignature = useMemo(
    () => JSON.stringify({
      tasks: data.tasks.map((task) => [task.id, task.status, task.updated_at]),
      proposals: (data.workflow_proposals || []).map((proposal) => [proposal.id, proposal.status, proposal.updated_at]),
      duplicates: (data.duplicates?.groups || []).map((group) => [group.entity_type, group.field, group.value, group.count]),
      filters: feedFilters
    }),
    [data, feedFilters]
  );
  const recordIndex = useMemo(() => buildRecordIndex(data), [data]);

  useEffect(() => {
    let isCurrent = true;
    async function loadOperations() {
      setIsLoadingOperations(true);
      try {
        const feed = await tryLoadOperationsFeed(feedFilters);
        if (!isCurrent) return;
        setOperationsFeed(feed);
        if (feed) {
          setAllWorkflowProposals([]);
          setAuditEvents([]);
          return;
        }
        const [proposalPayload, auditPayload] = await Promise.allSettled([
          callBackend<{ workflow_proposals?: WorkflowProposal[] }>({ action: 'crm.list_workflow_proposals', status: 'all', limit: 50 }),
          callBackend<{ events?: AuditEvent[] }>({ action: 'crm.audit_log', entity_type: 'all', limit: 20 })
        ]);
        if (!isCurrent) return;
        if (proposalPayload.status === 'fulfilled' && Array.isArray(proposalPayload.value.workflow_proposals)) {
          setAllWorkflowProposals(proposalPayload.value.workflow_proposals);
        } else {
          setAllWorkflowProposals([]);
        }
        if (auditPayload.status === 'fulfilled' && Array.isArray(auditPayload.value.events)) {
          setAuditEvents(auditPayload.value.events);
        } else {
          setAuditEvents([]);
        }
      } finally {
        if (isCurrent) setIsLoadingOperations(false);
      }
    }
    void loadOperations();
    return () => {
      isCurrent = false;
    };
  }, [dataSignature, feedFilters]);

  const bootstrapProposals = data.workflow_proposals || [];
  const proposalIndex = useMemo(() => buildProposalIndex([...bootstrapProposals, ...allWorkflowProposals]), [bootstrapProposals, allWorkflowProposals]);
  const feedByKey = useMemo(() => buildFeedIndex(operationsFeed), [operationsFeed]);
  const proposalSource = allWorkflowProposals.length ? allWorkflowProposals : bootstrapProposals;
  const toDoCards = operationsFeed
    ? toDoCardsFromFeed(feedByKey.to_do, recordIndex)
    : toDoCardsFromBootstrap(data.tasks, data.next_action_suggestions || [], recordIndex);
  const pendingProposals = operationsFeed
    ? proposalCardsFromFeed(feedByKey.to_approve, proposalIndex, recordIndex)
    : proposalSource.filter((proposal) => ['pending', 'approved'].includes(proposal.status)).map((proposal) => proposalCardFromProposal(proposal, recordIndex));
  const audits = operationsFeed ? auditCardsFromFeed(feedByKey.audit, recordIndex) : auditEvents.map((event) => auditCardFromEvent(event, recordIndex));
  const duplicateGroups = (data.duplicates?.groups || []).filter((group) => !resolvedDuplicateKeys.has(duplicateGroupKey(group)));
  const deckCounts = {
    to_do: operationsFeedCount(operationsFeed, 'to_do', toDoCards.length),
    approvals: operationsFeedCount(operationsFeed, 'to_approve', pendingProposals.length),
    audit: operationsFeedCount(operationsFeed, 'audit', audits.length),
    duplicates: duplicateGroups.length
  };
  const activeSignals = deckCounts.to_do + deckCounts.approvals + deckCounts.duplicates;

  async function openProposalReview(card: ProposalCard) {
    if (!card.proposalId) return;
    setProposalReview({ card, isLoading: true, error: '' });
    setPendingProposalAction(`${card.proposalId}:preview`);
    try {
      const payload = await onWorkflowProposalPreview(card.proposalId);
      setProposalReview((current) => (current?.card.proposalId === card.proposalId ? { ...current, preview: payload.preview, isLoading: false, error: '' } : current));
    } catch (previewError) {
      const message = previewError instanceof Error ? previewError.message : 'Unable to load proposal preview.';
      setProposalReview((current) => (current?.card.proposalId === card.proposalId ? { ...current, isLoading: false, error: message } : current));
    } finally {
      setPendingProposalAction('');
    }
  }

  async function runWorkflowAction(proposalId: string, action: WorkflowProposalAction) {
    setPendingProposalAction(`${proposalId}:${action}`);
    try {
      return await onWorkflowProposalAction(proposalId, action);
    } finally {
      setPendingProposalAction('');
    }
  }

  function openDuplicateReview(group: DuplicateGroup) {
    const records = group.records || [];
    const targetId = records[0]?.id || '';
    setDuplicateMergeNotice('');
    setDuplicateReview({
      group,
      targetId,
      sourceIds: records.map((record) => record.id).filter((id) => id && id !== targetId),
      isMerging: false,
      error: ''
    });
  }

  async function runDuplicateMerge() {
    if (!duplicateReview?.targetId || !duplicateReview.sourceIds.length) return;
    const { group, targetId, sourceIds } = duplicateReview;
    setDuplicateReview((current) => (current ? { ...current, isMerging: true, error: '' } : current));
    try {
      await callBackend({
        action: 'crm.merge_records',
        entity_type: group.entity_type,
        target_id: targetId,
        source_ids: sourceIds
      });
      setResolvedDuplicateKeys((current) => new Set([...current, duplicateGroupKey(group)]));
      setDuplicateMergeNotice(`Merged ${sourceIds.length} ${entityLabel(group.entity_type).toLowerCase()} source ${sourceIds.length === 1 ? 'record' : 'records'} into ${recordTitleById(group.records, targetId)}.`);
      setDuplicateReview(null);
      await onDuplicateMerge?.();
    } catch (mergeError) {
      const message = mergeError instanceof Error ? mergeError.message : 'Unable to merge duplicate records.';
      setDuplicateReview((current) => (current ? { ...current, isMerging: false, error: message } : current));
    }
  }

  return (
    <section className="pipeline-agent-deck" aria-label="Agent CRM deck">
      <header className="agent-deck-header">
        <div>
          <h2>Agent deck</h2>
          <p>{activeSignals} active signals</p>
        </div>
        <div className="agent-deck-metrics" aria-label="Agent deck summary">
          <Metric label="Next" value={deckCounts.to_do} />
          <Metric label="Approvals" value={deckCounts.approvals} />
          <Metric label="Duplicates" value={deckCounts.duplicates} />
          <Metric label="Audit" value={deckCounts.audit} />
        </div>
      </header>

      {isLoadingOperations ? <p className="operations-loading">Refreshing agent deck...</p> : null}
      <div className="agent-deck-grid">
        <section className="agent-deck-lane" aria-label="Next actions">
          <h3>Next actions</h3>
          <ToDoSection items={toDoCards.slice(0, 3)} select={select} />
        </section>
        <section className="agent-deck-lane" aria-label="Workflow approvals">
          <h3>Approvals</h3>
          <ProposalSection cards={pendingProposals.slice(0, 2)} emptyText="No approvals waiting." onPreview={openProposalReview} pendingAction={pendingProposalAction} />
        </section>
        <section className="agent-deck-lane" aria-label="Data quality">
          <h3>Data quality</h3>
          <DuplicateSection groups={duplicateGroups.slice(0, 2)} select={select} notice={duplicateMergeNotice} onReview={openDuplicateReview} />
        </section>
      </div>

      {proposalReview ? (
        <WorkflowProposalPreviewDialog
          review={proposalReview}
          pendingAction={pendingProposalAction}
          onClose={() => setProposalReview(null)}
          onAction={async (action) => {
            const ok = await runWorkflowAction(proposalReview.card.proposalId, action);
            if (ok) setProposalReview(null);
          }}
        />
      ) : null}
      {duplicateReview ? (
        <DuplicateReviewDialog
          review={duplicateReview}
          onClose={() => setDuplicateReview(null)}
          onChange={setDuplicateReview}
          onMerge={runDuplicateMerge}
        />
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ToDoSection({
  items,
  select
}: {
  items: ToDoCard[];
  select: (value: { entity: string; record: CrmRecord }) => void;
}) {
  if (!items.length) return <p className="operations-empty">Nothing open right now.</p>;
  return (
    <div className="operations-card-list">
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          className="operation-card"
          onClick={() => {
            if (item.record && item.entityType) select({ entity: item.entityType, record: item.record });
          }}
        >
          <span className="operation-card-title">{item.title}</span>
          <span className="operation-card-meta">
            {item.kind === 'task' ? <ClipboardList size={14} aria-hidden="true" /> : <Sparkles size={14} aria-hidden="true" />}
            <span>{toDoMetaLabel(item)}</span>
          </span>
          <span className="operation-card-reason">{item.reason || item.source}</span>
        </button>
      ))}
    </div>
  );
}

function ProposalSection({
  cards,
  emptyText,
  onPreview,
  pendingAction
}: {
  cards: ProposalCard[];
  emptyText: string;
  onPreview: (card: ProposalCard) => void;
  pendingAction: string;
}) {
  if (!cards.length) return <p className="operations-empty">{emptyText}</p>;
  return (
    <div className="operations-card-list">
      {cards.map((card) => (
        <ProposalCardView key={card.key} card={card} onPreview={onPreview} pendingAction={pendingAction} />
      ))}
    </div>
  );
}

function ProposalCardView({
  card,
  onPreview,
  pendingAction
}: {
  card: ProposalCard;
  onPreview: (card: ProposalCard) => void;
  pendingAction: string;
}) {
  const isLoadingPreview = pendingAction === `${card.proposalId}:preview`;
  return (
    <button type="button" className="operation-card operation-proposal-card" onClick={() => onPreview(card)} disabled={!card.proposalId || isLoadingPreview} aria-label={`Review ${card.title}`}>
      <div>
        <span className="operation-card-title">{card.title}</span>
        <span className="operation-card-meta">
          {card.status} · {recordLabel(card.entityType, card.entityId, card.record)} · {card.actionLabel}
        </span>
        <span className="operation-card-reason">{[card.source, card.reason].filter(Boolean).join(' · ') || dateLabel(card.updatedAt)}</span>
        {card.evidence.length ? (
          <span className="operation-evidence">
            {card.evidence.map((item) => <small key={item}>{item}</small>)}
          </span>
        ) : null}
      </div>
      <span className="workflow-review-indicator">
        <Eye size={14} aria-hidden="true" />
        <span>{isLoadingPreview ? 'Loading' : 'Review'}</span>
      </span>
    </button>
  );
}

function WorkflowProposalPreviewDialog({
  review,
  pendingAction,
  onClose,
  onAction
}: {
  review: ProposalReviewState;
  pendingAction: string;
  onClose: () => void;
  onAction: (action: WorkflowProposalAction) => Promise<void>;
}) {
  const preview = review.preview;
  const status = preview?.status || review.card.status;
  const hasValidationIssues = Boolean(preview?.validation_issues.length);
  const isActionPending = pendingAction.startsWith(`${review.card.proposalId}:`);
  const canReview = review.card.status === 'pending' || review.card.status === 'approved';
  const taskEntries = Object.entries(preview?.proposed_task || {}).filter(([, value]) => value !== '' && value !== undefined && value !== null);
  return (
    <div className="crm-detail-overlay" onMouseDown={onClose}>
      <section className="crm-detail-dialog crm-action-dialog workflow-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="workflow-preview-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="detail-header">
          <div>
            <small>Workflow proposal</small>
            <h2 id="workflow-preview-title">{review.card.title}</h2>
          </div>
          <button className="detail-close" type="button" onClick={onClose} aria-label="Close workflow proposal preview">
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <div className="workflow-preview-body">
          {review.isLoading ? <p className="operations-loading">Loading proposal preview...</p> : null}
          {review.error ? <p className="crm-alert">{review.error}</p> : null}
          {preview ? (
            <>
              <dl className="workflow-preview-summary">
                <div>
                  <dt>Action</dt>
                  <dd>{prettyLabel(preview.action_type || review.card.actionLabel)}</dd>
                </div>
                <div>
                  <dt>Target</dt>
                  <dd>{recordLabel(preview.target?.entity_type || review.card.entityType, preview.target?.id || review.card.entityId, review.card.record)}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>{status}</dd>
                </div>
              </dl>

              {hasValidationIssues ? (
                <div className="workflow-preview-issues" role="alert">
                  <span>
                    <AlertTriangle size={15} aria-hidden="true" />
                    Validation issues
                  </span>
                  <ul>
                    {preview.validation_issues.map((issue) => (
                      <li key={issue}>{issue}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {preview.changes.length ? (
                <section className="workflow-preview-section" aria-label="Fields to change">
                  <h3>Fields to change</h3>
                  <div className="workflow-preview-change-list">
                    {preview.changes.map((change) => (
                      <div key={change.field}>
                        <span>{fieldLabel(change.field)}</span>
                        <code>{formatPreviewValue(change.current_value)}</code>
                        <strong aria-hidden="true">-&gt;</strong>
                        <code>{formatPreviewValue(change.proposed_value)}</code>
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}

              {taskEntries.length ? (
                <section className="workflow-preview-section" aria-label="Task to create">
                  <h3>Task to create</h3>
                  <dl className="workflow-preview-task">
                    {taskEntries.map(([field, value]) => (
                      <div key={field}>
                        <dt>{fieldLabel(field)}</dt>
                        <dd>{formatPreviewValue(value)}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              ) : null}
            </>
          ) : null}
        </div>

        {canReview ? (
          <div className="composer-actions workflow-preview-actions">
            <button type="button" onClick={() => onAction('dismiss')} disabled={isActionPending} title="Dismiss workflow proposal">
              <X size={15} aria-hidden="true" />
              <span>Dismiss</span>
            </button>
            <button type="button" onClick={() => onAction('reject')} disabled={isActionPending} title="Reject workflow proposal">
              <Ban size={15} aria-hidden="true" />
              <span>Reject</span>
            </button>
            {status === 'pending' ? (
              <button type="button" onClick={() => onAction('approve')} disabled={review.isLoading || hasValidationIssues || isActionPending} aria-label={`Approve ${review.card.title}`}>
                <Check size={15} aria-hidden="true" />
                <span>Approve</span>
              </button>
            ) : null}
            {status === 'approved' ? (
              <button type="button" onClick={() => onAction('apply')} disabled={review.isLoading || hasValidationIssues || isActionPending} aria-label={`Apply ${review.card.title}`}>
                <Play size={15} aria-hidden="true" />
                <span>Apply</span>
              </button>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}

function DuplicateSection({
  groups,
  select,
  notice,
  onReview
}: {
  groups: DuplicateGroup[];
  select: (value: { entity: string; record: CrmRecord }) => void;
  notice: string;
  onReview: (group: DuplicateGroup) => void;
}) {
  if (!groups.length) {
    return (
      <div className="operations-card-list">
        {notice ? <p className="operations-success">{notice}</p> : null}
        <p className="operations-empty">No duplicate groups detected.</p>
      </div>
    );
  }
  return (
    <div className="operations-card-list">
      {notice ? <p className="operations-success">{notice}</p> : null}
      {groups.slice(0, 20).map((group) => (
        <article key={`${group.entity_type}:${group.field}:${group.value}`} className="operation-card operation-duplicate-card">
          <div>
            <span className="operation-card-title">{group.value}</span>
            <span className="operation-card-meta">
              {group.count} {entityLabel(group.entity_type).toLowerCase()} records · {group.field}
            </span>
            <div className="duplicate-record-list" aria-label={`${group.value} duplicate records`}>
              {(group.records || []).map((record) => (
                <button key={record.id} type="button" onClick={() => select({ entity: group.entity_type, record })}>
                  <span>{titleFor(record)}</span>
                  <small>{duplicateRecordMeta(record)}</small>
                </button>
              ))}
            </div>
          </div>
          <button type="button" onClick={() => onReview(group)} disabled={(group.records || []).length < 2} aria-label={`Review duplicate ${group.value}`}>
            <Search size={14} aria-hidden="true" />
            <span>Review</span>
          </button>
        </article>
      ))}
    </div>
  );
}

function DuplicateReviewDialog({
  review,
  onClose,
  onChange,
  onMerge
}: {
  review: DuplicateReviewState;
  onClose: () => void;
  onChange: (value: DuplicateReviewState) => void;
  onMerge: () => Promise<void>;
}) {
  const records = review.group.records || [];
  const target = records.find((record) => record.id === review.targetId);
  const sources = records.filter((record) => review.sourceIds.includes(record.id));
  const canMerge = Boolean(review.targetId && review.sourceIds.length);

  function chooseTarget(recordId: string) {
    onChange({
      ...review,
      targetId: recordId,
      sourceIds: records.map((record) => record.id).filter((id) => id && id !== recordId),
      error: ''
    });
  }

  function toggleSource(recordId: string) {
    if (recordId === review.targetId) return;
    const nextSources = review.sourceIds.includes(recordId) ? review.sourceIds.filter((id) => id !== recordId) : [...review.sourceIds, recordId];
    onChange({ ...review, sourceIds: nextSources, error: '' });
  }

  return (
    <div className="crm-detail-overlay" onMouseDown={onClose}>
      <section className="crm-detail-dialog crm-action-dialog duplicate-review-dialog" role="dialog" aria-modal="true" aria-labelledby="duplicate-review-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="detail-header">
          <div>
            <small>Duplicate merge review</small>
            <h2 id="duplicate-review-title">Merge duplicate records</h2>
          </div>
          <button className="detail-close" type="button" onClick={onClose} aria-label="Close duplicate merge review">
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <div className="workflow-preview-body">
          {review.error ? <p className="crm-alert">{review.error}</p> : null}
          <dl className="workflow-preview-summary">
            <div>
              <dt>Group</dt>
              <dd>{review.group.value}</dd>
            </div>
            <div>
              <dt>Match</dt>
              <dd>{fieldLabel(review.group.field)}</dd>
            </div>
            <div>
              <dt>Records</dt>
              <dd>{records.length}</dd>
            </div>
          </dl>

          <section className="workflow-preview-section" aria-label="Choose duplicate merge target and sources">
            <h3>Records</h3>
            <div className="duplicate-review-records">
              {records.map((record) => (
                <article key={record.id} className={record.id === review.targetId ? 'active' : ''}>
                  <strong>{titleFor(record)}</strong>
                  <span>{duplicateRecordMeta(record)}</span>
                  <label>
                    <input type="radio" name="duplicate-target" checked={record.id === review.targetId} onChange={() => chooseTarget(record.id)} aria-label={`Use ${titleFor(record)} as target`} />
                    <span>Target</span>
                  </label>
                  <label>
                    <input type="checkbox" checked={review.sourceIds.includes(record.id)} disabled={record.id === review.targetId} onChange={() => toggleSource(record.id)} aria-label={`Use ${titleFor(record)} as source`} />
                    <span>Source</span>
                  </label>
                </article>
              ))}
            </div>
          </section>

          <section className="workflow-preview-section" aria-label="Duplicate field differences">
            <h3>Differences</h3>
            <div className="duplicate-diff-list">
              {duplicateDiffRows(records).map((row) => (
                <div key={row.field}>
                  <span>{fieldLabel(row.field)}</span>
                  {records.map((record) => (
                    <code key={`${row.field}:${record.id}`} className={record.id === review.targetId ? 'active' : ''}>
                      {row.values[record.id]}
                    </code>
                  ))}
                </div>
              ))}
            </div>
          </section>

          <section className="workflow-preview-section" aria-label="Merge result">
            <h3>Merge</h3>
            <p className="duplicate-merge-summary">
              Target: {target ? titleFor(target) : 'None'} · Sources: {sources.length ? sources.map((record) => titleFor(record)).join(', ') : 'None selected'}
            </p>
          </section>
        </div>

        <div className="composer-actions workflow-preview-actions">
          <button type="button" onClick={onClose} disabled={review.isMerging} title="Cancel duplicate merge">
            <X size={15} aria-hidden="true" />
            <span>Cancel</span>
          </button>
          <button type="button" onClick={onMerge} disabled={!canMerge || review.isMerging} aria-label="Merge duplicate records">
            <GitMerge size={15} aria-hidden="true" />
            <span>{review.isMerging ? 'Merging' : 'Merge'}</span>
          </button>
        </div>
      </section>
    </div>
  );
}

function operationsFeedFilters(filters: OperationsFilters) {
  const status = (filters.status || '').trim();
  const statusLower = status.toLowerCase();
  const dueOverdue = truthyFilter(filters.due_overdue) || statusLower === 'overdue' || statusLower === 'past_due';
  const payload: Record<string, unknown> = {};
  if (filters.owner_id) payload.owner_id = filters.owner_id;
  if (filters.kind) payload.kind = filters.kind;
  if (filters.due_before) payload.due_before = filters.due_before;
  if (dueOverdue) payload.due_overdue = true;
  if (status && !dueOverdue) payload.status = status;
  if (dueOverdue && !filters.kind) payload.kind = 'task';
  if (dueOverdue && !payload.status) payload.status = 'open';
  return payload;
}

function truthyFilter(value: unknown) {
  if (typeof value === 'boolean') return value;
  if (typeof value !== 'string') return Boolean(value);
  return ['1', 'true', 'yes', 'on', 'overdue'].includes(value.trim().toLowerCase());
}

async function tryLoadOperationsFeed(filters: Record<string, unknown>) {
  try {
    const feed = await callBackend<OperationsFeedPayload>({ action: 'crm.operations_feed', limit: 20, ...filters });
    return Array.isArray(feed.sections) ? feed : null;
  } catch {
    return null;
  }
}

function buildRecordIndex(data: BootstrapPayload) {
  const records = [
    ...data.leads.map((record) => ['lead', record] as const),
    ...data.accounts.map((record) => ['account', record] as const),
    ...data.contacts.map((record) => ['contact', record] as const),
    ...data.deals.map((record) => ['deal', record] as const),
    ...data.tasks.map((record) => ['task', record] as const),
    ...data.notes.map((record) => ['note', record] as const),
    ...data.activities.map((record) => ['activity', record] as const)
  ];
  return new Map(records.map(([entity, record]) => [`${entity}:${record.id}`, record]));
}

function buildProposalIndex(proposals: WorkflowProposal[]) {
  return new Map(proposals.map((proposal) => [proposal.id, proposal]));
}

function buildFeedIndex(feed: OperationsFeedPayload | null) {
  const index: Record<string, OperationsFeedItem[]> = {};
  for (const section of feed?.sections || []) {
    index[section.key] = Array.isArray(section.items) ? section.items : [];
  }
  return index;
}

function operationsFeedCount(feed: OperationsFeedPayload | null, key: OperationsFeedSectionKey, fallback: number) {
  const count = feed?.counts?.[key];
  if (typeof count === 'number') return count;
  const sectionCount = feed?.sections?.find((section) => section.key === key)?.count;
  return typeof sectionCount === 'number' ? sectionCount : fallback;
}

function toDoCardsFromFeed(items: OperationsFeedItem[] = [], recordIndex: Map<string, CrmRecord>) {
  return uniqueToDoCards(items.map((item) => toDoCardFromFeedItem(item, recordIndex)));
}

function toDoCardFromFeedItem(item: OperationsFeedItem, recordIndex: Map<string, CrmRecord>): ToDoCard {
  const entityType = item.ref?.entity_type || '';
  const entityId = item.ref?.entity_id || '';
  const record = recordIndex.get(`${entityType}:${entityId}`);
  return {
    key: `feed:${item.kind}:${entityType}:${entityId}:${item.title || item.reason || item.source}`,
    kind: item.kind || 'task',
    title: item.title || (item.kind === 'recommendation' ? 'Recommended next action' : 'Task'),
    status: item.status || '',
    entityType,
    entityId,
    record,
    source: item.source || '',
    reason: item.reason || '',
    priority: item.priority,
    score: item.score,
    dueAt: item.due_at,
    updatedAt: item.updated_at || item.created_at
  };
}

function toDoCardsFromBootstrap(tasks: CrmRecord[], suggestions: NonNullable<BootstrapPayload['next_action_suggestions']>, recordIndex: Map<string, CrmRecord>) {
  const openTasks = tasks.filter((task) => task.status === 'open').map((task) => toDoCardFromTask(task));
  const taskKeys = new Set(openTasks.flatMap((item) => [...toDoDedupeKeys(item)]));
  const recommendationCards = suggestions
    .map((action) => toDoCardFromSuggestion(action, recordIndex))
    .filter((item) => ![...toDoDedupeKeys(item)].some((key) => taskKeys.has(key)));
  return uniqueToDoCards([...openTasks, ...recommendationCards]);
}

function toDoCardFromTask(task: CrmRecord): ToDoCard {
  return {
    key: `task:${task.id}`,
    kind: 'task',
    title: titleFor(task),
    status: String(task.status || 'open'),
    entityType: 'task',
    entityId: task.id,
    record: task,
    source: 'crm.tasks',
    reason: String(task.priority || task.body || 'CRM task'),
    priority: typeof task.priority === 'string' ? task.priority : undefined,
    dueAt: typeof task.due_at === 'string' ? task.due_at : undefined,
    updatedAt: typeof task.updated_at === 'string' ? task.updated_at : undefined
  };
}

function toDoCardFromSuggestion(action: NonNullable<BootstrapPayload['next_action_suggestions']>[number], recordIndex: Map<string, CrmRecord>): ToDoCard {
  const record = action.record || recordIndex.get(`${action.entity_type}:${action.entity_id}`);
  return {
    key: `recommendation:${action.kind}:${action.entity_type}:${action.entity_id}:${action.title}`,
    kind: 'recommendation',
    title: action.title,
    status: 'recommended',
    entityType: action.entity_type,
    entityId: action.entity_id,
    record,
    source: 'crm.next_actions',
    reason: action.reason || action.kind,
    score: action.score
  };
}

function uniqueToDoCards(items: ToDoCard[]) {
  const seen = new Set<string>();
  const unique: ToDoCard[] = [];
  for (const item of items) {
    const keys = toDoDedupeKeys(item);
    if ([...keys].some((key) => seen.has(key))) continue;
    for (const key of keys) seen.add(key);
    unique.push(item);
  }
  return unique;
}

function toDoDedupeKeys(item: ToDoCard) {
  const keys = new Set<string>();
  if (item.entityType && item.entityId) keys.add(`${item.entityType}:${item.entityId}`);
  if (item.kind && item.title) keys.add(`${item.kind}:${item.title}`);
  if (item.record) {
    for (const [field, entityType] of [
      ['account_id', 'account'],
      ['contact_id', 'contact'],
      ['deal_id', 'deal']
    ] as const) {
      const value = item.record[field];
      if (typeof value === 'string' && value) keys.add(`${entityType}:${value}`);
    }
    const metadata = item.record.metadata;
    if (metadata && typeof metadata === 'object' && !Array.isArray(metadata)) {
      const leadId = (metadata as Record<string, unknown>).lead_id;
      if (typeof leadId === 'string' && leadId) keys.add(`lead:${leadId}`);
    }
  }
  return keys;
}

function proposalCardsFromFeed(items: OperationsFeedItem[] = [], proposalIndex: Map<string, WorkflowProposal>, recordIndex: Map<string, CrmRecord>) {
  return items.filter((item) => item.kind === 'workflow_proposal').map((item) => proposalCardFromFeedItem(item, proposalIndex, recordIndex));
}

function proposalCardFromFeedItem(item: OperationsFeedItem, proposalIndex: Map<string, WorkflowProposal>, recordIndex: Map<string, CrmRecord>): ProposalCard {
  const proposalId = item.ref?.proposal_id || '';
  const proposal = proposalIndex.get(proposalId);
  const entityType = proposal?.entity_type || item.ref?.entity_type || '';
  const entityId = proposal?.entity_id || item.ref?.entity_id || '';
  return {
    key: `feed:${proposalId || item.title}:${entityType}:${entityId}`,
    proposalId,
    title: proposal?.title || item.title || 'Workflow proposal',
    status: proposal?.status || item.status || 'pending',
    entityType,
    entityId,
    record: recordIndex.get(`${entityType}:${entityId}`),
    actionLabel: workflowActionLabel(proposal, item.action_type),
    source: proposal?.source || item.source || '',
    reason: item.reason || proposalReason(proposal),
    evidence: item.evidence || [],
    updatedAt: proposal?.updated_at || item.updated_at || item.created_at,
    proposal
  };
}

function proposalCardFromProposal(proposal: WorkflowProposal, recordIndex: Map<string, CrmRecord>): ProposalCard {
  return {
    key: `proposal:${proposal.id}`,
    proposalId: proposal.id,
    title: proposal.title,
    status: proposal.status,
    entityType: proposal.entity_type,
    entityId: proposal.entity_id,
    record: recordIndex.get(`${proposal.entity_type}:${proposal.entity_id}`),
    actionLabel: workflowActionLabel(proposal),
    source: proposal.source || 'crm.workflow',
    reason: proposalReason(proposal),
    evidence: proposalEvidence(proposal),
    updatedAt: proposal.updated_at,
    proposal
  };
}

function auditCardsFromFeed(items: OperationsFeedItem[] = [], recordIndex: Map<string, CrmRecord>) {
  return items.filter((item) => item.kind === 'audit_event').map((item) => {
    const entityType = item.ref?.entity_type || '';
    const entityId = item.ref?.entity_id || '';
    return {
      key: `audit:${item.ref?.event_id || item.title}:${entityType}:${entityId}`,
      title: item.title || 'audit event',
      entityType,
      entityId,
      record: recordIndex.get(`${entityType}:${entityId}`),
      source: item.source || 'crm.audit',
      reason: item.reason || item.status || '',
      createdAt: item.created_at
    };
  });
}

function auditCardFromEvent(event: AuditEvent, recordIndex: Map<string, CrmRecord>): AuditCard {
  const entityType = event.entity_type || '';
  const entityId = event.entity_id || '';
  const payload = event.payload || {};
  return {
    key: `audit:${event.id}`,
    title: event.event_type || 'audit event',
    entityType,
    entityId,
    record: recordIndex.get(`${entityType}:${entityId}`),
    source: 'crm.audit',
    reason: String(payload.reason || payload.action_type || payload.proposal_type || ''),
    createdAt: event.created_at
  };
}

function workflowActionLabel(proposal?: WorkflowProposal, feedActionType?: string) {
  const action = proposal?.proposal?.action || {};
  const actionType = typeof action.type === 'string' ? action.type : feedActionType || proposal?.proposal_type || 'proposal';
  if (actionType === 'create_task' && typeof action.title === 'string') return action.title;
  if (actionType === 'update_record') return 'Update record';
  return prettyLabel(actionType);
}

function proposalReason(proposal?: WorkflowProposal) {
  const reason = proposal?.proposal?.reason;
  return typeof reason === 'string' ? reason : '';
}

function proposalEvidence(proposal?: WorkflowProposal) {
  const raw = proposal?.proposal?.evidence;
  if (!Array.isArray(raw)) return proposal?.status === 'pending' ? ['requires approval'] : [];
  return raw.map((item) => typeof item === 'string' ? item : '').filter(Boolean).slice(0, 5);
}

function recordLabel(entityType: string, entityId: string, record?: CrmRecord) {
  if (record) return `${entityLabel(entityType)}: ${titleFor(record)}`;
  if (entityType && entityId) return `${entityLabel(entityType)}: ${entityId}`;
  return 'No record';
}

function duplicateGroupKey(group: DuplicateGroup) {
  return `${group.entity_type}:${group.field}:${group.value}`;
}

function recordTitleById(records: CrmRecord[], id: string) {
  return titleFor(records.find((record) => record.id === id) || { id });
}

function duplicateRecordMeta(record: CrmRecord) {
  return [
    stringField(record.email) || stringField(record.domain),
    stringField(record.owner_id),
    stringField(record.status)
  ].filter(Boolean).join(' · ') || record.id;
}

function duplicateDiffRows(records: CrmRecord[]) {
  const fields = ['name', 'display_name', 'email', 'domain', 'owner_id', 'status', 'summary', 'tags', 'custom_fields'];
  return fields.map((field) => ({
    field,
    values: Object.fromEntries(records.map((record) => [record.id, duplicateFieldValue(record, field)]))
  })).filter((row) => new Set(Object.values(row.values)).size > 1 || Object.values(row.values).some((value) => value !== 'Empty'));
}

function duplicateFieldValue(record: CrmRecord, field: string) {
  if (field === 'tags') {
    const tags = Array.isArray(record.tags) ? record.tags : [];
    const names = tags.map((tag) => (tag && typeof tag === 'object' ? stringField((tag as { name?: unknown }).name) : stringField(tag))).filter(Boolean);
    return names.length ? names.join(', ') : 'Empty';
  }
  if (field === 'custom_fields') {
    return formatPreviewValue(record.custom_fields);
  }
  return formatPreviewValue(record[field]);
}

function stringField(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : '';
}

function toDoMetaLabel(item: ToDoCard) {
  const labels = [item.kind === 'task' ? item.status || 'open' : 'recommended'];
  const target = recordLabel(item.entityType, item.entityId, item.record);
  if (target !== 'No record' && item.entityType !== 'task') labels.push(target);
  if (item.dueAt || item.updatedAt) labels.push(dateLabel(item.dueAt || item.updatedAt));
  if (typeof item.score === 'number') labels.push(`score ${item.score}`);
  return labels.filter(Boolean).join(' · ');
}

function dateLabel(value: unknown) {
  return typeof value === 'string' && value ? value.slice(0, 10) : 'No date';
}

function prettyLabel(value: string) {
  return value.replace(/_/g, ' ');
}

function fieldLabel(value: string) {
  return prettyLabel(value.replace(/^custom_fields\./, 'custom field '));
}

function formatPreviewValue(value: unknown) {
  if (value === null || value === undefined || value === '') return 'Empty';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
