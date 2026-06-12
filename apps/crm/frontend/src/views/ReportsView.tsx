import { Activity, CalendarDays, ClipboardList, Mail, Percent, ShieldAlert, TrendingUp } from 'lucide-react';
import { CrmRecord } from '../api';
import { PipelineStageReport, SalesReportsPayload } from '../domain/types';
import { money } from '../domain/routing';

type ReportsViewProps = {
  reports: SalesReportsPayload | null;
  isLoading: boolean;
  onOpenStage: (stage: string) => void;
  onOpenDeal: (record: CrmRecord) => void;
  onOpenAgentDeck: (filters: Record<string, string>) => void;
};

export function ReportsView({ reports, isLoading, onOpenStage, onOpenDeal, onOpenAgentDeck }: ReportsViewProps) {
  const stages = reports?.pipeline_value_by_stage || [];
  const forecast = reports?.weighted_forecast || {};
  const conversion = reports?.lead_conversion || {};
  const overdue = reports?.task_overdue || {};
  const activities = reports?.activities_by_owner || [];
  const connections = reports?.connection_metrics || {};
  const openPipelineTotals = sumByCurrency(stages, 'total_value');
  const openDealCount = stages.reduce((total, item) => total + Number(item.deal_count || 0), 0);
  const overdueFilters = overdue.drilldown_filters || { kind: 'task', status: 'open', due_overdue: 'true' };
  const kpis: Array<{ label: string; value: string; icon: typeof TrendingUp; onClick?: () => void }> = [
    { label: 'Open deals', value: String(openDealCount), icon: TrendingUp },
    { label: 'Open pipeline', value: formatCurrencyTotals(openPipelineTotals), icon: TrendingUp },
    { label: 'Weighted forecast', value: formatCurrencyTotals(forecast.currency_totals, '') || formatMoney(forecast.total_weighted_value, 'EUR'), icon: TrendingUp },
    { label: 'Lead conversion', value: percent(conversion.conversion_rate), icon: Percent },
    { label: 'Linked email leads', value: String(connections.leads_with_linked_email || 0), icon: Mail },
    { label: 'Deals with calls', value: String(connections.deals_with_scheduled_call || 0), icon: CalendarDays },
    { label: 'Pending approvals', value: String(connections.records_with_pending_approvals || 0), icon: ShieldAlert, onClick: () => onOpenAgentDeck({ kind: 'workflow_proposal', status: 'pending' }) },
    { label: 'Overdue tasks', value: String(overdue.total || 0), icon: ClipboardList, onClick: () => onOpenAgentDeck(overdueFilters) }
  ];

  return (
    <div className="reports-view">
      <section className="crm-metrics" aria-label="Sales report summary">
        {kpis.map((metric) => {
          const Icon = metric.icon;
          const body = (
            <>
              <Icon aria-hidden="true" />
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
            </>
          );
          return metric.onClick ? (
            <button className="metric" key={metric.label} type="button" onClick={metric.onClick}>
              {body}
            </button>
          ) : (
            <div className="metric" key={metric.label}>
              {body}
            </div>
          );
        })}
      </section>
      {isLoading ? <p className="muted">Loading reports...</p> : null}

      <div className="reports-grid">
        <section className="crm-panel">
          <h2>Forecast by currency</h2>
          <div className="report-list">
            {currencyEntries(forecast.currency_totals).map(([currency, value]) => (
              <div className="report-row" key={currency}>
                <strong>{currency || 'Unspecified'}</strong>
                <span>{formatMoney(value, currency || 'EUR')}</span>
              </div>
            ))}
            {!currencyEntries(forecast.currency_totals).length ? <EmptyReport text="No forecast value yet." /> : null}
          </div>
        </section>

        <section className="crm-panel">
          <h2>Agentic connections</h2>
          <div className="report-list">
            <div className="report-row">
              <strong>Accounts without follow-up</strong>
              <span>{connections.accounts_without_recent_follow_up || 0}</span>
            </div>
            <div className="report-row">
              <strong>Pipeline with next call</strong>
              <span>{formatCurrencyTotals(connections.pipeline_value_with_next_call)}</span>
            </div>
            <div className="report-row">
              <strong>Records pending approval</strong>
              <span>{connections.records_with_pending_approvals || 0}</span>
            </div>
          </div>
        </section>

        <section className="crm-panel">
          <h2>Lead conversion</h2>
          <div className="report-conversion">
            <strong>{percent(conversion.conversion_rate)}</strong>
            <span>{conversion.converted || 0} converted from {conversion.total || 0} leads</span>
            <span>{numberLabel(conversion.avg_days_to_convert)} average days to convert</span>
          </div>
        </section>
      </div>

      <section className="crm-panel">
        <h2>Pipeline by stage</h2>
        <div className="report-list">
          {stages.map((item) => {
            const stage = item.stage || item.stage_id || 'Unspecified';
            return (
              <button key={`${item.stage_id || stage}:${item.currency || ''}`} type="button" className="report-row" onClick={() => onOpenStage(stage)}>
                <strong>{stage}</strong>
                <span>{item.deal_count || 0} deals · {formatMoney(item.total_value, item.currency || 'EUR')} · weighted {formatMoney(item.weighted_value, item.currency || 'EUR')}</span>
              </button>
            );
          })}
          {!stages.length ? <EmptyReport text="No open pipeline by stage." /> : null}
        </div>
      </section>

      <div className="reports-grid">
        <section className="crm-panel">
          <h2>Overdue tasks by owner</h2>
          <div className="report-list">
            {(overdue.by_owner || []).map((item) => {
              const owner = item.owner_id || 'Unassigned';
              return (
                <button key={owner} type="button" className="report-row" onClick={() => onOpenAgentDeck(item.drilldown_filters || { owner_id: item.owner_id || '', kind: 'task', status: 'open', due_overdue: 'true' })}>
                  <strong>{owner}</strong>
                  <span>{item.task_count || 0} overdue tasks</span>
                </button>
              );
            })}
            {!overdue.by_owner?.length ? <EmptyReport text="No overdue tasks." /> : null}
          </div>
        </section>

        <section className="crm-panel">
          <h2>Activities by owner/type</h2>
          <div className="report-list">
            {activities.map((item) => {
              const owner = item.owner_id || 'Unassigned';
              return (
                <button key={owner} type="button" className="report-activity-row" onClick={() => onOpenAgentDeck(item.drilldown_filters || { owner_id: item.owner_id || '', kind: 'activity' })}>
                  <span>
                    <strong>{owner}</strong>
                    <em>{item.total || 0} activities</em>
                  </span>
                  <span className="report-type-chips">
                    {Object.entries(item.by_type || {}).map(([type, count]) => (
                      <small key={type}>{type}: {count}</small>
                    ))}
                  </span>
                </button>
              );
            })}
            {!activities.length ? <EmptyReport text="No activities recorded." /> : null}
          </div>
        </section>
      </div>

      <section className="crm-panel">
        <h2>Deal aging</h2>
        <div className="report-list">
          {(reports?.deal_aging || []).slice(0, 12).map((item) => (
            <button
              key={item.id || item.name}
              type="button"
              className="report-row"
              onClick={() => item.id && onOpenDeal({ ...item, id: item.id })}
            >
              <strong>{item.name || item.id}</strong>
              <span>{item.stage || 'No stage'} · {item.age_days || 0} days · {formatMoney(item.value, item.currency || 'EUR')}</span>
            </button>
          ))}
          {!reports?.deal_aging?.length ? <EmptyReport text="No aging deals." /> : null}
        </div>
      </section>
    </div>
  );
}

function EmptyReport({ text }: { text: string }) {
  return (
    <div className="report-empty">
      <Activity size={15} aria-hidden="true" />
      <span>{text}</span>
    </div>
  );
}

function sumByCurrency(rows: PipelineStageReport[], key: 'total_value' | 'weighted_value') {
  return rows.reduce<Record<string, number>>((totals, row) => {
    const currency = row.currency || 'EUR';
    totals[currency] = (totals[currency] || 0) + Number(row[key] || 0);
    return totals;
  }, {});
}

function currencyEntries(totals?: Record<string, number>) {
  return Object.entries(totals || {}).filter(([, value]) => Number(value || 0) !== 0);
}

function formatCurrencyTotals(totals?: Record<string, number>, emptyLabel = 'EUR 0') {
  const values = currencyEntries(totals).map(([currency, value]) => formatMoney(value, currency || 'EUR'));
  return values.length ? values.join(' · ') : emptyLabel;
}

function formatMoney(value = 0, currency = 'EUR') {
  return money({ value, currency }) || `${currency} 0`;
}

function percent(value = 0) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function numberLabel(value = 0) {
  const numberValue = Number(value || 0);
  return Number.isInteger(numberValue) ? String(numberValue) : numberValue.toFixed(1);
}
