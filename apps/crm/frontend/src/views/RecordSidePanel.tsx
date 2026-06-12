import { FormEvent, useEffect, useState } from 'react';
import { Archive, ArrowLeft, CopyCheck, MoreHorizontal, Pencil, Tag, Trash2, X } from 'lucide-react';
import { CrmRecord, callBackend } from '../api';
import { AccountBrief, AuditEvent, ConnectionSummary, EnrichmentResult, ExternalRef } from '../domain/types';
import { isCreatableEntity, titleFor } from '../domain/routing';
import {
  AgentSection,
  AuditSection,
  ConnectionSummarySection,
  CustomFieldsSection,
  DetailFields,
  DetailTags,
  LinkedItemsSection,
  LinkDraft,
  TimelineSection
} from './RecordSidePanelSections';

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
  const [connectionSummary, setConnectionSummary] = useState<ConnectionSummary | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditFilters, setAuditFilters] = useState({ entity_type: selected.entity, event_type: '', date_from: '', date_to: '' });
  const [linkDraft, setLinkDraft] = useState<LinkDraft>({ source_app_id: '', source_entity_type: '', source_entity_id: '', link_type: 'related', title: '', summary: '', occurred_at: '' });
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
    loadLinkedItems()
      .catch(() => {
        setLinkedItems([]);
        setConnectionSummary(null);
      });
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
    await loadLinkedItems();
  }

  async function loadLinkedItems() {
    if (['lead', 'account', 'contact', 'deal'].includes(selected.entity)) {
      const result = await callBackend<{ items?: ExternalRef[]; connection_summary?: ConnectionSummary }>({ action: 'crm.external_timeline', entity_type: selected.entity, id: selected.record.id });
      setLinkedItems(result.items || []);
      setConnectionSummary(result.connection_summary || null);
      return;
    }
    const result = await callBackend<{ external_refs?: ExternalRef[] }>({ action: 'crm.list_external_refs', crm_entity_type: selected.entity, crm_entity_id: selected.record.id });
    setLinkedItems(result.external_refs || []);
    setConnectionSummary(null);
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

  async function unlinkExternalItem(item: ExternalRef) {
    setDetailError('');
    if (item.relationship_scope === 'inherited') {
      setDetailError('Inherited links can only be unlinked from their source CRM record.');
      return;
    }
    setIsLinking(true);
    try {
      await callBackend({ action: 'crm.unlink_external_ref', id: item.id });
      await refreshLinkedItems();
      await refreshTimeline();
    } catch (unlinkError) {
      setDetailError(unlinkError instanceof Error ? unlinkError.message : 'Unable to unlink item.');
    } finally {
      setIsLinking(false);
    }
  }

  return (
    <section className="crm-detail-page" role="region" aria-labelledby="crm-detail-title">
      <header className="detail-header detail-page-header">
        <div className="detail-title-row">
          <button className="detail-back-button" type="button" onClick={onClose}>
            <ArrowLeft size={17} aria-hidden="true" />
            <span>Back</span>
          </button>
          <div>
            <small>{selected.entity}</small>
            <h2 id="crm-detail-title">{titleFor(selected.record)}</h2>
          </div>
        </div>
        <div className="detail-actions">
          <details className="detail-secondary-actions">
            <summary className="detail-icon-button detail-overflow-trigger" aria-label="More record actions" title="More record actions">
              <MoreHorizontal size={17} aria-hidden="true" />
            </summary>
            <div className="detail-secondary-menu" role="menu" aria-label="More record actions">
              {isCreatableEntity(selected.entity) ? (
                <button type="button" role="menuitem" onClick={() => onEdit(selected.entity, selected.record)} disabled={isSaving}>
                  <Pencil size={16} aria-hidden="true" />
                  <span>Edit record</span>
                </button>
              ) : null}
              <button type="button" role="menuitem" onClick={onTag} disabled={isSaving}>
                <Tag size={16} aria-hidden="true" />
                <span>Tag record</span>
              </button>
              {selected.entity === 'lead' && !selected.record.converted_at ? (
                <button type="button" role="menuitem" onClick={onConvertLead} disabled={isSaving}>
                  <CopyCheck size={16} aria-hidden="true" />
                  <span>Convert lead</span>
                </button>
              ) : null}
              <button type="button" role="menuitem" onClick={onArchive} disabled={isSaving}>
                <Archive size={16} aria-hidden="true" />
                <span>Archive record</span>
              </button>
              <button className="danger" type="button" role="menuitem" onClick={onDelete} disabled={isSaving}>
                <Trash2 size={16} aria-hidden="true" />
                <span>Delete record</span>
              </button>
            </div>
          </details>
          <button className="detail-close" type="button" onClick={onClose} aria-label="Close record details">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
      </header>
      <div className="detail-content">
        <DetailTags tags={tags} />
        {detailError ? <div className="crm-alert">{detailError}</div> : null}
        <DetailFields entity={selected.entity} record={selected.record} />
        <CustomFieldsSection customFields={customFields} />
        <ConnectionSummarySection summary={connectionSummary} linkedItems={linkedItems} />
        <AgentSection entity={selected.entity} brief={brief} enrichment={enrichment} isSaving={isSaving} onGenerateBrief={generateBrief} onEnrich={enrichRecord} />
        <LinkedItemsSection linkedItems={linkedItems} linkDraft={linkDraft} setLinkDraft={setLinkDraft} isSaving={isSaving} isLinking={isLinking} onLink={linkExternalItem} onUnlink={(item) => void unlinkExternalItem(item)} />
        <TimelineSection timeline={timeline} />
        <AuditSection auditFilters={auditFilters} setAuditFilters={setAuditFilters} auditEvents={auditEvents} />
      </div>
    </section>
  );
}
