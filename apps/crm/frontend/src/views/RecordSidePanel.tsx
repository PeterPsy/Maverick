import { FormEvent, useEffect, useState } from 'react';
import { Archive, CopyCheck, Link2, Pencil, Tag, Trash2, Unlink, X } from 'lucide-react';
import { CrmRecord, callBackend } from '../api';
import { AccountBrief, AuditEvent, EnrichmentResult, ExternalRef } from '../domain/types';
import { entityLabel, fieldLabel, isCreatableEntity, titleFor } from '../domain/routing';

export function RecordSidePanel({
  selected,
  isSaving,
  onClose,
  onEdit,
  onArchive,
  onDelete,
  onTag,
  onConvertLead
}: {
  selected: { entity: string; record: CrmRecord };
  isSaving: boolean;
  onClose: () => void;
  onEdit: (entity: string, record: CrmRecord) => void;
  onArchive: () => void;
  onDelete: () => void;
  onTag: () => void;
  onConvertLead: () => void;
}) {
  const tags = Array.isArray(selected.record.tags) ? selected.record.tags.filter((tag): tag is { name?: unknown; color?: unknown } => typeof tag === 'object' && tag !== null) : [];
  const customFields = selected.record.custom_fields && typeof selected.record.custom_fields === 'object' ? (selected.record.custom_fields as Record<string, unknown>) : {};
  const [timeline, setTimeline] = useState<CrmRecord[]>([]);
  const [linkedItems, setLinkedItems] = useState<ExternalRef[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditFilters, setAuditFilters] = useState({ entity_type: selected.entity, event_type: '', date_from: '', date_to: '' });
  const [linkDraft, setLinkDraft] = useState({ source_app_id: '', source_entity_type: '', source_entity_id: '', link_type: 'related', title: '', summary: '', occurred_at: '' });
  const [brief, setBrief] = useState<AccountBrief | null>(null);
  const [enrichment, setEnrichment] = useState<EnrichmentResult | null>(null);
  const [detailError, setDetailError] = useState('');
  const [isLinking, setIsLinking] = useState(false);

  useEffect(() => {
    if (!['lead', 'account', 'contact', 'deal'].includes(selected.entity)) {
      setTimeline([]);
      return;
    }
    callBackend<{ items?: CrmRecord[] }>({ action: 'crm.timeline', entity_type: selected.entity, id: selected.record.id })
      .then((result) => setTimeline(result.items || []))
      .catch(() => setTimeline([]));
  }, [selected.entity, selected.record.id]);

  useEffect(() => {
    callBackend<{ external_refs?: ExternalRef[] }>({ action: 'crm.list_external_refs', crm_entity_type: selected.entity, crm_entity_id: selected.record.id })
      .then((result) => setLinkedItems(result.external_refs || []))
      .catch(() => setLinkedItems([]));
  }, [selected.entity, selected.record.id]);

  useEffect(() => {
    setAuditFilters({ entity_type: selected.entity, event_type: '', date_from: '', date_to: '' });
  }, [selected.entity, selected.record.id]);

  useEffect(() => {
    const entityId = auditFilters.entity_type === selected.entity ? selected.record.id : '';
    callBackend<{ events?: AuditEvent[] }>({
      action: 'crm.audit_log',
      entity_type: auditFilters.entity_type || selected.entity,
      entity_id: entityId,
      event_type: auditFilters.event_type,
      date_from: auditFilters.date_from,
      date_to: auditFilters.date_to,
      limit: 20
    })
      .then((result) => setAuditEvents(result.events || []))
      .catch(() => setAuditEvents([]));
  }, [auditFilters, selected.entity, selected.record.id]);

  async function refreshLinkedItems() {
    const result = await callBackend<{ external_refs?: ExternalRef[] }>({ action: 'crm.list_external_refs', crm_entity_type: selected.entity, crm_entity_id: selected.record.id });
    setLinkedItems(result.external_refs || []);
  }

  async function refreshTimeline() {
    if (!['lead', 'account', 'contact', 'deal'].includes(selected.entity)) return;
    const result = await callBackend<{ items?: CrmRecord[] }>({ action: 'crm.timeline', entity_type: selected.entity, id: selected.record.id });
    setTimeline(result.items || []);
  }

  async function generateBrief() {
    if (selected.entity !== 'account') return;
    setDetailError('');
    try {
      setBrief(await callBackend<AccountBrief>({ action: 'crm.account_brief', account_id: selected.record.id }));
    } catch (briefError) {
      setDetailError(briefError instanceof Error ? briefError.message : 'Unable to generate account brief.');
    }
  }

  async function enrichRecord() {
    setDetailError('');
    try {
      setEnrichment(await callBackend<EnrichmentResult>({ action: 'crm.record_enrichment', entity_type: selected.entity, id: selected.record.id, create_proposal: true }));
    } catch (enrichError) {
      setDetailError(enrichError instanceof Error ? enrichError.message : 'Unable to enrich record.');
    }
  }

  async function linkExternalItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setDetailError('');
    setIsLinking(true);
    try {
      await callBackend({
        action: 'crm.link_external_ref',
        crm_entity_type: selected.entity,
        crm_entity_id: selected.record.id,
        source_app_id: linkDraft.source_app_id,
        source_entity_type: linkDraft.source_entity_type,
        source_entity_id: linkDraft.source_entity_id,
        link_type: linkDraft.link_type || 'related',
        title: linkDraft.title,
        summary: linkDraft.summary,
        occurred_at: linkDraft.occurred_at
      });
      setLinkDraft({ source_app_id: '', source_entity_type: '', source_entity_id: '', link_type: 'related', title: '', summary: '', occurred_at: '' });
      await refreshLinkedItems();
      await refreshTimeline();
    } catch (linkError) {
      setDetailError(linkError instanceof Error ? linkError.message : 'Unable to link item.');
    } finally {
      setIsLinking(false);
    }
  }

  async function unlinkExternalItem(id: string) {
    setDetailError('');
    setIsLinking(true);
    try {
      await callBackend({ action: 'crm.unlink_external_ref', id });
      await refreshLinkedItems();
      await refreshTimeline();
    } catch (unlinkError) {
      setDetailError(unlinkError instanceof Error ? unlinkError.message : 'Unable to unlink item.');
    } finally {
      setIsLinking(false);
    }
  }

  return (
    <div className="crm-detail-drawer" role="presentation">
      <button className="crm-detail-scrim" type="button" onClick={onClose} aria-label="Close record details" />
      <aside className="crm-detail-side-panel" role="dialog" aria-modal="false" aria-labelledby="crm-detail-title">
        <header className="detail-header">
          <div>
            <small>{selected.entity}</small>
            <h2 id="crm-detail-title">{titleFor(selected.record)}</h2>
          </div>
          <div className="detail-actions">
            {isCreatableEntity(selected.entity) ? (
              <button className="detail-icon-button" type="button" onClick={() => onEdit(selected.entity, selected.record)} aria-label="Edit record" disabled={isSaving}>
                <Pencil size={17} aria-hidden="true" />
              </button>
            ) : null}
            <button className="detail-icon-button" type="button" onClick={onTag} aria-label="Tag record" disabled={isSaving}>
              <Tag size={17} aria-hidden="true" />
            </button>
            {selected.entity === 'lead' && !selected.record.converted_at ? (
              <button className="detail-icon-button" type="button" onClick={onConvertLead} aria-label="Convert lead" disabled={isSaving}>
                <CopyCheck size={17} aria-hidden="true" />
              </button>
            ) : null}
            {selected.entity === 'account' ? (
              <button className="detail-text-button" type="button" onClick={generateBrief} disabled={isSaving}>
                Brief
              </button>
            ) : null}
            <button className="detail-text-button" type="button" onClick={enrichRecord} disabled={isSaving}>
              Enrich
            </button>
            <button className="detail-icon-button" type="button" onClick={onArchive} aria-label="Archive record" disabled={isSaving}>
              <Archive size={17} aria-hidden="true" />
            </button>
            <button className="detail-icon-button danger" type="button" onClick={onDelete} aria-label="Delete record" disabled={isSaving}>
              <Trash2 size={17} aria-hidden="true" />
            </button>
            <button className="detail-close" type="button" onClick={onClose} aria-label="Close record details">
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </header>
        {tags.length ? (
          <div className="detail-tags">
            {tags.map((tag) => (
              <span key={String(tag.name)} style={typeof tag.color === 'string' && tag.color ? { borderColor: tag.color } : undefined}>
                {String(tag.name)}
              </span>
            ))}
          </div>
        ) : null}
        {detailError ? <div className="crm-alert">{detailError}</div> : null}
        <dl className="detail-fields">
          {Object.entries(selected.record)
            .filter(([, value]) => value !== '' && value !== null && value !== undefined && typeof value !== 'object')
            .slice(0, 16)
            .map(([key, value]) => (
              <div key={key}>
                <dt>{fieldLabel(key)}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))}
        </dl>
        {Object.keys(customFields).length ? (
          <section className="detail-timeline">
            <h3>Custom fields</h3>
            {Object.entries(customFields).map(([key, value]) => (
              <div key={key}>
                <strong>{fieldLabel(key)}</strong>
                <span>{Array.isArray(value) ? value.join(', ') : String(value ?? '')}</span>
              </div>
            ))}
          </section>
        ) : null}
        {brief ? (
          <section className="detail-timeline">
            <h3>Account brief</h3>
            <p className="muted">{brief.brief}</p>
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
          </section>
        ) : null}
        {enrichment ? (
          <section className="detail-timeline">
            <h3>Enrichment</h3>
            {enrichment.suggestions?.length ? enrichment.suggestions.map((suggestion) => (
              <div key={`${suggestion.field}:${String(suggestion.value)}`}>
                <strong>{String(suggestion.field)}</strong>
                <span>{String(suggestion.value ?? '')} · {suggestion.reason}</span>
              </div>
            )) : <p className="muted">No enrichment suggestions.</p>}
            {enrichment.workflow_proposal?.id ? <p className="muted">Proposal {enrichment.workflow_proposal.id} created for approval.</p> : null}
          </section>
        ) : null}
        <section className="detail-linked-items">
          <h3>Linked items</h3>
          {linkedItems.length ? (
            <div className="linked-list">
              {linkedItems.map((item) => (
                <article key={item.id}>
                  <Link2 size={16} aria-hidden="true" />
                  <div>
                    <strong>{item.title || `${item.source_app_id}:${item.source_entity_type}`}</strong>
                    <span>{[item.source_app_id, item.source_entity_type, item.source_entity_id].filter(Boolean).join(' / ')}</span>
                    {item.summary ? <p>{item.summary}</p> : null}
                  </div>
                  <button type="button" className="detail-icon-button" onClick={() => void unlinkExternalItem(item.id)} disabled={isSaving || isLinking} aria-label="Unlink item">
                    <Unlink size={15} aria-hidden="true" />
                  </button>
                </article>
              ))}
            </div>
          ) : (
            <p className="muted">No linked items.</p>
          )}
          <form className="linked-form" onSubmit={linkExternalItem}>
            <input aria-label="Source app id" placeholder="source app" value={linkDraft.source_app_id} onChange={(event) => setLinkDraft((draft) => ({ ...draft, source_app_id: event.target.value }))} required />
            <input aria-label="Source entity type" placeholder="entity type" value={linkDraft.source_entity_type} onChange={(event) => setLinkDraft((draft) => ({ ...draft, source_entity_type: event.target.value }))} required />
            <input aria-label="Source entity id" placeholder="entity id" value={linkDraft.source_entity_id} onChange={(event) => setLinkDraft((draft) => ({ ...draft, source_entity_id: event.target.value }))} required />
            <input aria-label="Link type" placeholder="link type" value={linkDraft.link_type} onChange={(event) => setLinkDraft((draft) => ({ ...draft, link_type: event.target.value }))} />
            <input aria-label="Title" placeholder="title" value={linkDraft.title} onChange={(event) => setLinkDraft((draft) => ({ ...draft, title: event.target.value }))} />
            <input aria-label="Occurred at" placeholder="occurred at" value={linkDraft.occurred_at} onChange={(event) => setLinkDraft((draft) => ({ ...draft, occurred_at: event.target.value }))} />
            <textarea aria-label="Summary" placeholder="summary" value={linkDraft.summary} onChange={(event) => setLinkDraft((draft) => ({ ...draft, summary: event.target.value }))} />
            <button type="submit" disabled={isSaving || isLinking}>
              <Link2 size={15} aria-hidden="true" />
              Link
            </button>
          </form>
        </section>
        <section className="detail-audit">
          <h3>Audit</h3>
          <div className="audit-filters">
            <select aria-label="Audit entity" value={auditFilters.entity_type} onChange={(event) => setAuditFilters((filters) => ({ ...filters, entity_type: event.target.value }))}>
              {['all', 'lead', 'account', 'contact', 'deal', 'activity', 'task', 'note'].map((entity) => (
                <option key={entity} value={entity}>{entityLabel(entity)}</option>
              ))}
            </select>
            <input aria-label="Audit action" placeholder="action" value={auditFilters.event_type} onChange={(event) => setAuditFilters((filters) => ({ ...filters, event_type: event.target.value }))} />
            <input aria-label="Audit date from" placeholder="from" value={auditFilters.date_from} onChange={(event) => setAuditFilters((filters) => ({ ...filters, date_from: event.target.value }))} />
            <input aria-label="Audit date to" placeholder="to" value={auditFilters.date_to} onChange={(event) => setAuditFilters((filters) => ({ ...filters, date_to: event.target.value }))} />
          </div>
          {auditEvents.length ? (
            <div className="audit-list">
              {auditEvents.map((event) => (
                <div key={event.id}>
                  <strong>{event.event_type}</strong>
                  <span>{[event.entity_type, event.entity_id].filter(Boolean).join(' / ')}</span>
                  <span>{String(event.created_at || '').slice(0, 16)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No audit events.</p>
          )}
        </section>
        {timeline.length ? (
          <section className="detail-timeline">
            <h3>Timeline</h3>
            {timeline.slice(0, 8).map((item) => (
              <div key={`${item.entity_type || 'event'}:${item.id}`}>
                <strong>{String(item.subject || item.title || item.event_type || titleFor(item))}</strong>
                <span>{String(item.timestamp || item.updated_at || item.created_at || '').slice(0, 16)}</span>
              </div>
            ))}
          </section>
        ) : null}
      </aside>
    </div>
  );
}
