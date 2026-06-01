import { Dispatch, FormEvent, SetStateAction } from 'react';
import { CalendarDays, FileText, Link2, Mail, ShieldAlert, Sparkles, Unlink } from 'lucide-react';
import { CrmRecord } from '../api';
import { AccountBrief, AuditEvent, ConnectionBadge, ConnectionSummary, EnrichmentResult, ExternalRef } from '../domain/types';
import { entityLabel, fieldLabel, money, titleFor } from '../domain/routing';

export type LinkDraft = {
  source_app_id: string;
  source_entity_type: string;
  source_entity_id: string;
  link_type: string;
  title: string;
  summary: string;
  occurred_at: string;
};

type AuditFilters = {
  entity_type: string;
  event_type: string;
  date_from: string;
  date_to: string;
};

export function DetailTags({ tags }: { tags: Array<{ name?: unknown; color?: unknown }> }) {
  if (!tags.length) return null;
  return (
    <div className="detail-tags">
      {tags.map((tag) => (
        <span key={String(tag.name)} style={typeof tag.color === 'string' && tag.color ? { borderColor: tag.color } : undefined}>
          {String(tag.name)}
        </span>
      ))}
    </div>
  );
}

type DetailField = {
  key: string;
  label: string;
  format?: 'date' | 'datetime' | 'money' | 'percent';
};

const commonDetailFields: DetailField[] = [
  { key: 'owner_id', label: 'Owner' },
  { key: 'status', label: 'Status' },
  { key: 'summary', label: 'Summary' },
  { key: 'created_at', label: 'Created', format: 'datetime' },
  { key: 'updated_at', label: 'Updated', format: 'datetime' }
];

const detailFieldsByEntity: Record<string, DetailField[]> = {
  lead: [
    { key: 'display_name', label: 'Lead' },
    { key: 'company', label: 'Company' },
    { key: 'email', label: 'Email' },
    { key: 'phone', label: 'Phone' },
    { key: 'domain', label: 'Website' },
    { key: 'source', label: 'Source' },
    { key: 'status', label: 'Status' },
    { key: 'owner_id', label: 'Owner' },
    { key: 'summary', label: 'Summary' },
    { key: 'converted_at', label: 'Converted', format: 'datetime' },
    { key: 'updated_at', label: 'Updated', format: 'datetime' }
  ],
  account: [
    { key: 'name', label: 'Account' },
    { key: 'domain', label: 'Website' },
    { key: 'industry', label: 'Industry' },
    { key: 'status', label: 'Status' },
    { key: 'owner_id', label: 'Owner' },
    { key: 'summary', label: 'Summary' },
    { key: 'created_at', label: 'Created', format: 'datetime' },
    { key: 'updated_at', label: 'Updated', format: 'datetime' }
  ],
  contact: [
    { key: 'display_name', label: 'Contact' },
    { key: 'email', label: 'Email' },
    { key: 'phone', label: 'Phone' },
    { key: 'role', label: 'Role' },
    { key: 'account_id', label: 'Account' },
    { key: 'owner_id', label: 'Owner' },
    { key: 'summary', label: 'Summary' },
    { key: 'updated_at', label: 'Updated', format: 'datetime' }
  ],
  deal: [
    { key: 'name', label: 'Deal' },
    { key: 'stage', label: 'Stage' },
    { key: 'value', label: 'Value', format: 'money' },
    { key: 'probability', label: 'Probability', format: 'percent' },
    { key: 'close_date', label: 'Close date', format: 'date' },
    { key: 'account_id', label: 'Account' },
    { key: 'contact_id', label: 'Contact' },
    { key: 'owner_id', label: 'Owner' },
    { key: 'summary', label: 'Summary' },
    { key: 'updated_at', label: 'Updated', format: 'datetime' }
  ],
  task: [
    { key: 'title', label: 'Task' },
    { key: 'status', label: 'Status' },
    { key: 'priority', label: 'Priority' },
    { key: 'due_at', label: 'Due', format: 'datetime' },
    { key: 'account_id', label: 'Account' },
    { key: 'contact_id', label: 'Contact' },
    { key: 'deal_id', label: 'Deal' },
    { key: 'owner_id', label: 'Owner' },
    { key: 'body', label: 'Notes' },
    { key: 'updated_at', label: 'Updated', format: 'datetime' }
  ],
  note: [
    { key: 'body', label: 'Note' },
    { key: 'account_id', label: 'Account' },
    { key: 'contact_id', label: 'Contact' },
    { key: 'deal_id', label: 'Deal' },
    { key: 'owner_id', label: 'Owner' },
    { key: 'updated_at', label: 'Updated', format: 'datetime' }
  ],
  activity: [
    { key: 'activity_type', label: 'Type' },
    { key: 'subject', label: 'Subject' },
    { key: 'body', label: 'Notes' },
    { key: 'occurred_at', label: 'Occurred', format: 'datetime' },
    { key: 'due_at', label: 'Due', format: 'datetime' },
    { key: 'completed_at', label: 'Completed', format: 'datetime' },
    { key: 'account_id', label: 'Account' },
    { key: 'contact_id', label: 'Contact' },
    { key: 'deal_id', label: 'Deal' },
    { key: 'owner_id', label: 'Owner' }
  ]
};

export function DetailFields({ entity, record }: { entity: string; record: CrmRecord }) {
  const fields = (detailFieldsByEntity[entity] || commonDetailFields)
    .map((field) => ({ ...field, value: formatDetailValue(record, field) }))
    .filter((field) => field.value);

  if (!fields.length) return null;
  return (
    <dl className="detail-fields">
      {fields.map((field) => (
        <div key={field.key}>
          <dt>{field.label}</dt>
          <dd>{field.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function formatDetailValue(record: CrmRecord, field: DetailField) {
  const value = record[field.key];
  if (value === '' || value === null || value === undefined || typeof value === 'object') return '';
  if (field.format === 'money') return money({ value: Number(value), currency: String(record.currency || 'EUR') });
  if (field.format === 'percent') {
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue)) return String(value);
    return `${numberValue > 1 ? Math.round(numberValue) : Math.round(numberValue * 100)}%`;
  }
  if (field.format === 'date') return formatDate(value, false);
  if (field.format === 'datetime') return formatDate(value, true);
  return String(value);
}

function formatDate(value: unknown, includeTime: boolean) {
  const text = String(value || '').trim();
  if (!text) return '';
  const [date, rawTime = ''] = text.replace('T', ' ').split(' ');
  const time = rawTime.replace(/Z$/, '').slice(0, 5);
  return includeTime && time ? `${date} ${time}` : date;
}

export function CustomFieldsSection({ customFields }: { customFields: Record<string, unknown> }) {
  if (!Object.keys(customFields).length) return null;
  return (
    <section className="detail-timeline">
      <h3>Custom fields</h3>
      {Object.entries(customFields).map(([key, value]) => (
        <div key={key}>
          <strong>{fieldLabel(key)}</strong>
          <span>{Array.isArray(value) ? value.join(', ') : String(value ?? '')}</span>
        </div>
      ))}
    </section>
  );
}

export function AgentSection({
  entity,
  brief,
  enrichment,
  isSaving,
  onGenerateBrief,
  onEnrich
}: {
  entity: string;
  brief: AccountBrief | null;
  enrichment: EnrichmentResult | null;
  isSaving: boolean;
  onGenerateBrief: () => void;
  onEnrich: () => void;
}) {
  const canBrief = entity === 'account';
  return (
    <section className="detail-agent">
      <div className="detail-section-heading">
        <div>
          <h3>Agent</h3>
          <p>Briefs and enrichment suggestions for this record.</p>
        </div>
        <div>
          {canBrief ? (
            <button type="button" onClick={onGenerateBrief} disabled={isSaving}>
              Brief
            </button>
          ) : null}
          <button type="button" onClick={onEnrich} disabled={isSaving}>
            <Sparkles size={15} aria-hidden="true" />
            Enrich
          </button>
        </div>
      </div>
      {brief ? (
        <div className="agent-block">
          <h4>Account brief</h4>
          {brief.brief ? <p>{brief.brief}</p> : null}
          {brief.risks?.map((risk) => (
            <div key={risk}>
              <strong>Risk</strong>
              <span>{risk}</span>
            </div>
          ))}
          {brief.opportunities?.map((opportunity) => (
            <div key={opportunity}>
              <strong>Opportunity</strong>
              <span>{opportunity}</span>
            </div>
          ))}
        </div>
      ) : null}
      {enrichment ? (
        <div className="agent-block">
          <h4>Enrichment</h4>
          {enrichment.suggestions?.length ? enrichment.suggestions.map((suggestion) => (
            <div key={`${suggestion.field}:${String(suggestion.value)}`}>
              <strong>{fieldLabel(String(suggestion.field || 'Suggestion'))}</strong>
              <span>{String(suggestion.value ?? '')}{suggestion.reason ? ` - ${suggestion.reason}` : ''}</span>
            </div>
          )) : <p className="muted">No enrichment suggestions.</p>}
          {enrichment.workflow_proposal?.id ? <p className="muted">Proposal {enrichment.workflow_proposal.id} created for approval.</p> : null}
        </div>
      ) : null}
      {!brief && !enrichment ? <p className="muted">No agent output yet.</p> : null}
    </section>
  );
}

export function ConnectionSummarySection({ summary, linkedItems }: { summary: ConnectionSummary | null; linkedItems: ExternalRef[] }) {
  const badges = summary?.badges?.filter((badge) => badge.count || badge.label) || [];
  const visibleBadges = badges.length ? badges : summary?.total_count ? [{ key: 'connections', kind: 'connections', label: `Connections ${summary.total_count}`, count: summary.total_count }] : [];
  if (!summary || (!visibleBadges.length && !summary.approval_count)) return null;
  return (
    <section className="detail-connection-summary">
      <h3>Connection summary</h3>
      <div className="connection-summary-grid">
        {visibleBadges.map((badge) => {
          const Icon = summaryIcon(badge);
          return (
            <div key={badge.key || badge.kind || badge.label || 'connection'}>
              <Icon size={15} aria-hidden="true" />
              <strong>{badge.label || summaryLabel(badge)}</strong>
              <span>{summaryDetail(badge, summary, linkedItems)}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export function LinkedItemsSection({
  linkedItems,
  linkDraft,
  setLinkDraft,
  isSaving,
  isLinking,
  onLink,
  onUnlink
}: {
  linkedItems: ExternalRef[];
  linkDraft: LinkDraft;
  setLinkDraft: Dispatch<SetStateAction<LinkDraft>>;
  isSaving: boolean;
  isLinking: boolean;
  onLink: (event: FormEvent<HTMLFormElement>) => void;
  onUnlink: (item: ExternalRef) => void;
}) {
  const hasReferenceTarget = Boolean(
    linkDraft.source_app_id.trim() &&
    linkDraft.source_entity_type.trim() &&
    linkDraft.source_entity_id.trim()
  );
  const isManualLinkDisabled = isSaving || isLinking || !hasReferenceTarget;

  return (
    <section className="detail-linked-items">
      <h3>Linked mail, calendar, and files</h3>
      {linkedItems.length ? (
        <div className="linked-list">
          {linkedItems.map((item) => (
            <article key={item.id}>
              <Link2 size={16} aria-hidden="true" />
              <div>
                <strong>{item.title || `${item.source_app_id}:${item.source_entity_type}`}</strong>
                <span className="linked-meta">{[item.source_app_id || 'Unknown app', item.source_entity_type || 'Item', item.link_type || 'related'].filter(Boolean).join(' - ')}</span>
                <span className={isInheritedRef(item) ? 'linked-origin inherited' : 'linked-origin'}>
                  {originLabel(item)}
                </span>
                {item.occurred_at || item.timestamp ? <span>{formatDate(item.occurred_at || item.timestamp, true)}</span> : null}
                {item.summary ? <p>{item.summary}</p> : null}
                {sourceDeepLink(item) ? (
                  <a className="linked-source-link" href={sourceDeepLink(item)} onClick={(event) => event.stopPropagation()}>
                    Open source
                  </a>
                ) : null}
                {item.source_entity_id ? (
                  <details className="linked-technical">
                    <summary>Reference details</summary>
                    <span>{item.source_entity_id}</span>
                  </details>
                ) : null}
              </div>
              <button
                type="button"
                className="detail-icon-button"
                onClick={() => onUnlink(item)}
                disabled={isSaving || isLinking || isInheritedRef(item)}
                aria-label={isInheritedRef(item) ? 'Inherited link cannot be unlinked here' : 'Unlink item'}
                title={isInheritedRef(item) ? 'Inherited links can only be unlinked from their source CRM record.' : 'Unlink item'}
              >
                <Unlink size={15} aria-hidden="true" />
              </button>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted">No linked items.</p>
      )}
      <details className="linked-manual">
        <summary>Manual reference</summary>
        <form className="linked-form" onSubmit={onLink}>
          <p className="linked-form-note">Reference target required</p>
          <input aria-label="Title" placeholder="Title" value={linkDraft.title} onChange={(event) => setLinkDraft((draft) => ({ ...draft, title: event.target.value }))} />
          <input aria-label="Date" placeholder="Date" value={linkDraft.occurred_at} onChange={(event) => setLinkDraft((draft) => ({ ...draft, occurred_at: event.target.value }))} />
          <textarea aria-label="Summary" placeholder="Summary" value={linkDraft.summary} onChange={(event) => setLinkDraft((draft) => ({ ...draft, summary: event.target.value }))} />
          <details className="linked-advanced">
            <summary>Advanced reference fields</summary>
            <div>
              <input aria-label="Source app id" placeholder="App" value={linkDraft.source_app_id} onChange={(event) => setLinkDraft((draft) => ({ ...draft, source_app_id: event.target.value }))} />
              <input aria-label="Source entity type" placeholder="Type" value={linkDraft.source_entity_type} onChange={(event) => setLinkDraft((draft) => ({ ...draft, source_entity_type: event.target.value }))} />
              <input aria-label="Source entity id" placeholder="Record ID" value={linkDraft.source_entity_id} onChange={(event) => setLinkDraft((draft) => ({ ...draft, source_entity_id: event.target.value }))} />
              <input aria-label="Link type" placeholder="Relationship" value={linkDraft.link_type} onChange={(event) => setLinkDraft((draft) => ({ ...draft, link_type: event.target.value }))} />
            </div>
          </details>
          <button type="submit" disabled={isManualLinkDisabled} aria-disabled={isManualLinkDisabled}>
            <Link2 size={15} aria-hidden="true" />
            Link
          </button>
        </form>
      </details>
    </section>
  );
}

export function AuditSection({
  auditFilters,
  setAuditFilters,
  auditEvents
}: {
  auditFilters: AuditFilters;
  setAuditFilters: Dispatch<SetStateAction<AuditFilters>>;
  auditEvents: AuditEvent[];
}) {
  return (
    <details className="detail-audit">
      <summary>
        <span>Audit trail</span>
        <small>{auditEvents.length ? `${auditEvents.length} events` : 'No events'}</small>
      </summary>
      <div className="audit-filters">
        <select aria-label="Audit entity" value={auditFilters.entity_type} onChange={(event) => setAuditFilters((filters) => ({ ...filters, entity_type: event.target.value }))}>
          {['all', 'lead', 'account', 'contact', 'deal', 'activity', 'task', 'note'].map((entity) => (
            <option key={entity} value={entity}>{entityLabel(entity)}</option>
          ))}
        </select>
        <input aria-label="Audit action" placeholder="Action" value={auditFilters.event_type} onChange={(event) => setAuditFilters((filters) => ({ ...filters, event_type: event.target.value }))} />
        <input aria-label="Audit date from" placeholder="From" value={auditFilters.date_from} onChange={(event) => setAuditFilters((filters) => ({ ...filters, date_from: event.target.value }))} />
        <input aria-label="Audit date to" placeholder="To" value={auditFilters.date_to} onChange={(event) => setAuditFilters((filters) => ({ ...filters, date_to: event.target.value }))} />
      </div>
      {auditEvents.length ? (
        <div className="audit-list">
          {auditEvents.map((event) => (
            <div key={event.id}>
              <strong>{event.event_type || 'Change'}</strong>
              <span>{entityLabel(event.entity_type || '')}</span>
              <span>{formatDate(event.created_at, true)}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">No audit events.</p>
      )}
    </details>
  );
}

export function TimelineSection({ timeline }: { timeline: CrmRecord[] }) {
  if (!timeline.length) return null;
  return (
    <section className="detail-timeline">
      <h3>Timeline</h3>
      {timeline.slice(0, 8).map((item) => (
        <div key={`${item.entity_type || 'event'}:${item.id}`}>
          <strong>{String(item.subject || item.title || item.event_type || titleFor(item))}</strong>
          <span>{String(item.timestamp || item.updated_at || item.created_at || '').slice(0, 16)}</span>
        </div>
      ))}
    </section>
  );
}

function sourceDeepLink(item: ExternalRef) {
  const app = String(item.source_app_id || '').trim();
  const metadata = item.metadata && typeof item.metadata === 'object' ? item.metadata : {};
  const explicit = stringMetadata(metadata.deep_link) || stringMetadata(metadata.href) || stringMetadata(metadata.url) || stringMetadata(metadata.source_url);
  if (isAllowedLink(explicit)) return explicit;
  const appPage = stringMetadata(metadata.app_page);
  if (app && appPage && !appPage.startsWith('/') && !appPage.includes('://')) {
    return `/app/${encodeURIComponent(app)}/${appPage.split('/').map(encodeURIComponent).join('/')}`;
  }
  return '';
}

function stringMetadata(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function isAllowedLink(value: string) {
  return Boolean(value && (value.startsWith('/app/') || value.startsWith('https://')));
}

function summaryIcon(badge: ConnectionBadge) {
  const kind = String(badge.kind || badge.key || '').toLowerCase();
  if (kind.includes('mail')) return Mail;
  if (kind.includes('calendar')) return CalendarDays;
  if (kind.includes('file')) return FileText;
  if (kind.includes('approval')) return ShieldAlert;
  return Sparkles;
}

function summaryLabel(badge: ConnectionBadge) {
  const kind = String(badge.kind || badge.key || 'Connection');
  return `${entityLabel(kind)}${badge.count ? ` ${badge.count}` : ''}`;
}

function summaryDetail(badge: ConnectionBadge, summary: ConnectionSummary, linkedItems: ExternalRef[]) {
  const kind = String(badge.kind || badge.key || '').toLowerCase();
  if (kind.includes('approval')) return `${badge.count || summary.approval_count || 0} pending approval${(badge.count || summary.approval_count || 0) === 1 ? '' : 's'}`;
  if (kind.includes('agent')) return `${badge.count || summary.agent_count || 0} agent activit${(badge.count || summary.agent_count || 0) === 1 ? 'y' : 'ies'}`;
  if (kind.includes('calendar') && summary.next_calendar_at) return `Next ${formatDate(summary.next_calendar_at, true)}`;
  const latest = linkedItems.find((item) => {
    const refKind = String(badge.kind || badge.key || '').toLowerCase();
    return refKind && refKind.replace(/s$/, '') === normalizedProviderKind(item).replace(/s$/, '');
  });
  return latest?.title || latest?.summary || (summary.latest_touch_at ? `Latest ${formatDate(summary.latest_touch_at, true)}` : 'Linked business context');
}

function normalizedProviderKind(item: ExternalRef) {
  const provider = String(item.provider_alias || '').toLowerCase();
  if (provider) return provider;
  const sourceInterface = String(item.source_interface || '').toLowerCase();
  if (sourceInterface.startsWith('mail.')) return 'mail';
  if (sourceInterface.startsWith('calendar.')) return 'calendar';
  if (sourceInterface.startsWith('file.') || sourceInterface.startsWith('files.') || sourceInterface.startsWith('storage.')) return 'files';
  if (sourceInterface.startsWith('agent.')) return 'agent';
  const linkType = String(item.normalized_link_type || item.link_type || '').toLowerCase();
  if (['email', 'email_thread', 'mail', 'mail_thread', 'thread'].includes(linkType)) return 'mail';
  if (['call', 'meeting', 'sales_call', 'calendar_event', 'event'].includes(linkType)) return 'calendar';
  if (['attachment', 'brief', 'document', 'file', 'file_attachment'].includes(linkType)) return 'files';
  if (['agent_activity', 'agent_run'].includes(linkType)) return 'agent';
  return '';
}

function isInheritedRef(item: ExternalRef) {
  return item.relationship_scope === 'inherited';
}

function originLabel(item: ExternalRef) {
  if (!isInheritedRef(item)) return 'Direct link';
  const origin = item.origin || {};
  const entity = entityLabel(String(origin.entity_type || item.crm_entity_type || 'record'));
  const title = String(origin.title || origin.entity_id || item.crm_entity_id || '').trim();
  return title ? `Inherited from ${entity}: ${title}` : `Inherited from ${entity}`;
}
