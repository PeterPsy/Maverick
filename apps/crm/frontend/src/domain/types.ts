import { BootstrapPayload, CrmRecord, IntelligentNextAction, PipelineStage } from '../api';

export type ViewId = 'records' | 'pipeline' | 'reports' | 'import';
export type RecordEntityFilter = 'all' | 'lead' | 'account' | 'contact' | 'deal';
export type PendingSelection = { entity: string; id: string } | null;
export type ImportPreview = { ok?: boolean; row_count?: number; counts?: Record<string, number>; warnings?: string[]; errors?: Array<{ row: number; errors: string[] }> };
export type EntityRecord = { entity: string; record: CrmRecord };
export type CreatableEntity = 'lead' | 'account' | 'contact' | 'deal' | 'task' | 'note';
export type AccountBrief = { brief?: string; metrics?: Record<string, unknown>; risks?: string[]; opportunities?: string[]; next_actions?: IntelligentNextAction[] };
export type EnrichmentResult = { suggestions?: Array<{ field?: string; value?: unknown; confidence?: number; reason?: string }>; workflow_proposal?: { id?: string; title?: string } };
export type ExternalRef = {
  id: string;
  crm_entity_type?: string;
  crm_entity_id?: string;
  source_app_id?: string;
  source_entity_type?: string;
  source_entity_id?: string;
  link_type?: string;
  provider_alias?: string;
  source_interface?: string;
  normalized_link_type?: string;
  title?: string;
  summary?: string;
  occurred_at?: string;
  timestamp?: string;
  relationship_scope?: 'direct' | 'inherited';
  origin?: {
    entity_type?: string;
    entity_id?: string;
    title?: string;
  };
  metadata?: Record<string, unknown>;
};
export type ConnectionBadge = {
  key?: string;
  kind?: string;
  label?: string;
  count?: number;
  date?: string;
};
export type ConnectionSummary = {
  total_count?: number;
  mail_count?: number;
  calendar_count?: number;
  file_count?: number;
  agent_count?: number;
  approval_count?: number;
  latest_touch_at?: string;
  next_calendar_at?: string;
  has_recent_touch?: boolean;
  brief_ready?: boolean;
  badges?: ConnectionBadge[];
};
export type PipelineStageReport = {
  stage?: string;
  stage_id?: string;
  deal_count?: number;
  total_value?: number;
  weighted_value?: number;
  currency?: string;
};
export type DrilldownFilters = Record<string, string>;
export type SalesReportsPayload = {
  pipeline_value_by_stage?: PipelineStageReport[];
  weighted_forecast?: {
    currency_totals?: Record<string, number>;
    total_weighted_value?: number;
    by_stage?: PipelineStageReport[];
  };
  deal_aging?: Array<{ id?: string; name?: string; stage?: string; stage_id?: string; age_days?: number; value?: number; currency?: string; owner_id?: string; created_at?: string; updated_at?: string; close_date?: string }>;
  lead_conversion?: { total?: number; converted?: number; conversion_rate?: number; avg_days_to_convert?: number };
  connection_metrics?: {
    leads_with_linked_email?: number;
    deals_with_scheduled_call?: number;
    accounts_without_recent_follow_up?: number;
    records_with_pending_approvals?: number;
    pipeline_value_with_next_call?: Record<string, number>;
  };
  task_overdue?: { total?: number; drilldown_filters?: DrilldownFilters; by_owner?: Array<{ owner_id?: string; task_count?: number; drilldown_filters?: DrilldownFilters }> };
  activities_by_owner?: Array<{ owner_id?: string; total?: number; by_type?: Record<string, number>; drilldown_filters?: DrilldownFilters }>;
};
export type OperationsFilters = Record<string, string>;
export type AuditEvent = {
  id: string;
  event_type?: string;
  entity_type?: string;
  entity_id?: string;
  payload?: Record<string, unknown>;
  created_at?: string;
};
export type ComposerState =
  | { mode: 'create'; entity: CreatableEntity }
  | { mode: 'edit'; entity: CreatableEntity; record: CrmRecord }
  | null;

export type ActionDialogState =
  | { kind: 'save-view' }
  | { kind: 'record-tag' }
  | { kind: 'bulk-tag' }
  | { kind: 'pipeline-stage'; stage?: PipelineStage }
  | null;

export type MutatedRecordPayload = { record?: CrmRecord };

export const emptyPayload: BootstrapPayload = {
  ok: true,
  leads: [],
  accounts: [],
  contacts: [],
  deals: [],
  tasks: [],
  notes: [],
  activities: [],
  pipeline_stages: [],
  saved_views: [],
  duplicates: { groups: [] },
  workflow_proposals: [],
  counts: {},
  view_state: { view_filter: { mode: 'search', query: '', entity_type: 'all', refs: [], title: '' } }
};
