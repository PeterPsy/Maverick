import { MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react';
import { BootstrapPayload, CrmRecord, PipelineBoardPayload, PipelineBoardStage, PipelineStage } from '../api';
import { ConnectionSummary } from '../domain/types';
import { titleFor } from '../domain/routing';

export function Pipeline({
  board,
  data,
  select,
  onDeleteStage,
  onMoveDeal,
  onConfigureStage
}: {
  board?: PipelineBoardPayload | null;
  data: BootstrapPayload;
  select: (value: { entity: string; record: CrmRecord }) => void;
  onDeleteStage: (stage: PipelineStage) => void;
  onMoveDeal: (dealId: string, stageId: string) => void;
  onConfigureStage: (stage?: PipelineStage) => void;
}) {
  const accountLabels = new Map(data.accounts.map((account) => [account.id, titleFor(account)]));
  const contactLabels = new Map(data.contacts.map((contact) => [contact.id, titleFor(contact)]));
  const stages = board?.stages?.length ? board.stages : fallbackStages(data);

  return (
    <section className="pipeline-board">
      {stages.map((stage) => {
        const stageDeals = stage.deals || [];
        const totals = stage.totals && stage.weighted ? { total: stage.totals, weighted: stage.weighted } : stageTotals(stageDeals, stage);
        const dealCount = typeof stage.deal_count === 'number' ? stage.deal_count : stageDeals.length;
        return (
          <div
            className="pipeline-column"
            key={stage.id}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              const dealId = event.dataTransfer.getData('text/crm-deal-id');
              if (dealId) onMoveDeal(dealId, stage.id);
            }}
          >
            <h2>
              <span className="pipeline-stage-title">
                <strong>{stage.name}</strong>
                <span>
                  {dealCount} {dealCount === 1 ? 'deal' : 'deals'}
                </span>
              </span>
              <details className="pipeline-stage-actions">
                <summary aria-label={`${stage.name} stage options`} title={`${stage.name} stage options`}>
                  <MoreHorizontal size={14} aria-hidden="true" />
                </summary>
                <div role="menu" aria-label={`${stage.name} stage options`}>
                  <button type="button" role="menuitem" onClick={() => onConfigureStage(stage)}>
                    <Pencil size={14} aria-hidden="true" />
                    <span>Edit stage</span>
                  </button>
                  <button className="danger" type="button" role="menuitem" onClick={() => onDeleteStage(stage)}>
                    <Trash2 size={14} aria-hidden="true" />
                    <span>Delete stage</span>
                  </button>
                </div>
              </details>
            </h2>
            <div className="pipeline-stage-metrics" aria-label={`${stage.name} stage totals`}>
              <span>
                <small>Total</small>
                <strong>{formatCurrencyTotals(totals.total)}</strong>
              </span>
              <span>
                <small>Weighted</small>
                <strong>{formatCurrencyTotals(totals.weighted)}</strong>
              </span>
            </div>
            <div className="pipeline-deals">
              {stageDeals.map((deal) => {
                const accountLabel = labelFor(accountLabels, deal.account_id);
                const contactLabel = labelFor(contactLabels, deal.contact_id);
                const serverAccountLabel = stringField(deal.account_label);
                const serverContactLabel = stringField(deal.contact_label);
                const closeDateLabel = formatCloseDate(deal.close_date);
                const relationshipLabel = [serverAccountLabel || accountLabel, serverContactLabel || contactLabel].filter(Boolean).join(' / ');
                return (
                  <button
                    className="deal-card"
                    key={deal.id}
                    draggable
                    onClick={() => select({ entity: 'deal', record: deal })}
                    onDragStart={(event) => event.dataTransfer.setData('text/crm-deal-id', deal.id)}
                  >
                    <strong>{titleFor(deal)}</strong>
                    <span className="deal-card__value">{formatDealValue(deal)}</span>
                    {relationshipLabel ? <span className="deal-card__relationship">{relationshipLabel}</span> : null}
                    <DealConnectionBadges deal={deal} />
                    {closeDateLabel || deal.owner_id ? (
                      <span className="deal-card__meta">
                        {closeDateLabel ? <span>{closeDateLabel}</span> : null}
                        {deal.owner_id ? <span>Owner {String(deal.owner_id)}</span> : null}
                      </span>
                    ) : null}
                    <span className={`deal-card__health ${isStuck(deal) ? 'is-stuck' : ''}`}>{dealHealthLabel(deal)}</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
      <details className="pipeline-admin-actions">
        <summary aria-label="Pipeline admin actions" title="Pipeline admin actions">
          <MoreHorizontal size={15} aria-hidden="true" />
          <span>Pipeline options</span>
        </summary>
        <div role="menu" aria-label="Pipeline admin actions">
          <button type="button" role="menuitem" onClick={() => onConfigureStage()}>
            <Plus size={15} aria-hidden="true" />
            <span>Add stage</span>
          </button>
        </div>
      </details>
    </section>
  );
}

function DealConnectionBadges({ deal }: { deal: CrmRecord }) {
  const summary = deal.connection_summary && typeof deal.connection_summary === 'object' && !Array.isArray(deal.connection_summary)
    ? deal.connection_summary as ConnectionSummary
    : {};
  const badges = pipelineBadgeLabels(summary);
  if (!badges.length) return null;
  return (
    <span className="deal-card__connections" aria-label="Deal connections">
      {badges.map((badge) => (
        <small key={badge} className={badge === 'Needs approval' ? 'attention' : ''}>{badge}</small>
      ))}
    </span>
  );
}

function pipelineBadgeLabels(summary: ConnectionSummary) {
  const labels: string[] = [];
  if (summary.calendar_count) labels.push('Call booked');
  if (summary.brief_ready || summary.file_count) labels.push(summary.brief_ready ? 'Brief ready' : 'File linked');
  if (summary.mail_count) labels.push('Mail linked');
  if (summary.approval_count) labels.push('Needs approval');
  if (summary.has_recent_touch === false) labels.push('No recent touch');
  return labels.slice(0, 4);
}

function fallbackStages(data: BootstrapPayload): PipelineBoardStage[] {
  return data.pipeline_stages.map((stage) => ({
    ...stage,
    deals: data.deals.filter((deal) => deal.stage_id === stage.id || deal.stage === stage.name)
  }));
}

function labelFor(labels: Map<string, string>, id: unknown) {
  return typeof id === 'string' && id ? labels.get(id) || '' : '';
}

function stringField(value: unknown) {
  return typeof value === 'string' && value ? value : '';
}

function stageTotals(deals: CrmRecord[], stage: PipelineStage) {
  const total = new Map<string, number>();
  const weighted = new Map<string, number>();
  deals.forEach((deal) => {
    const currency = String(deal.currency || 'EUR');
    const value = numberValue(deal.value);
    total.set(currency, (total.get(currency) || 0) + value);
    weighted.set(currency, (weighted.get(currency) || 0) + value * probabilityFor(deal, stage));
  });
  return { total, weighted };
}

function probabilityFor(deal: CrmRecord, stage: PipelineStage) {
  const probability = numberValue(deal.probability, numberValue(stage.probability));
  return probability > 1 ? probability / 100 : probability;
}

function numberValue(value: unknown, fallback = 0) {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatCurrencyTotals(totals: Map<string, number> | Record<string, number> | undefined) {
  const entries = totals instanceof Map ? Array.from(totals.entries()) : Object.entries(totals || {});
  if (!entries.length) return 'EUR 0';
  return entries.map(([currency, value]) => formatCurrency(currency, value)).join(' / ');
}

function formatDealValue(deal: CrmRecord) {
  const value = numberValue(deal.value);
  if (!value) return 'No value';
  return formatCurrency(String(deal.currency || 'EUR'), value);
}

function formatCurrency(currency: string, value: number) {
  return `${currency || 'EUR'} ${value.toLocaleString('en-US', { maximumFractionDigits: value % 1 ? 2 : 0 })}`;
}

function formatCloseDate(value: unknown) {
  const date = dateFromValue(value);
  if (!date) return '';
  return `Close ${date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })}`;
}

function dealHealthLabel(deal: CrmRecord) {
  const health = deal.health;
  if (health && typeof health === 'object' && !Array.isArray(health) && typeof (health as { label?: unknown }).label === 'string') {
    return (health as { label: string }).label;
  }
  const age = daysSince(deal.created_at);
  const stale = daysSince(deal.updated_at);
  if (isPastDate(deal.close_date)) return 'Past due';
  if (stale !== null && stale >= 14) return `Stuck ${stale}d`;
  if (age !== null) return `Age ${age}d`;
  return 'Active';
}

function isStuck(deal: CrmRecord) {
  const health = deal.health;
  if (health && typeof health === 'object' && !Array.isArray(health)) {
    const typed = health as { is_stuck?: unknown; past_due?: unknown; status?: unknown };
    if (typeof typed.is_stuck === 'boolean') return typed.is_stuck;
    if (typed.status === 'stuck' || typed.status === 'past_due' || typed.past_due === true) return true;
  }
  const stale = daysSince(deal.updated_at);
  return isPastDate(deal.close_date) || (stale !== null && stale >= 14);
}

function daysSince(value: unknown) {
  const date = dateFromValue(value);
  if (!date) return null;
  return Math.max(0, Math.floor((Date.now() - date.getTime()) / 86_400_000));
}

function isPastDate(value: unknown) {
  const date = dateFromValue(value);
  if (!date) return false;
  const today = new Date();
  const startOfToday = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return date.getTime() < startOfToday;
}

function dateFromValue(value: unknown) {
  if (typeof value !== 'string' || !value) return null;
  const dateOnly = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (dateOnly) {
    const [, year, month, day] = dateOnly;
    return new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}
