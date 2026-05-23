import { BootstrapPayload, CrmRecord, IntelligentNextAction } from '../api';

export type ViewId = 'records' | 'pipeline' | 'operations' | 'reports' | 'import';
export type RecordEntityFilter = 'all' | 'lead' | 'account' | 'contact' | 'deal';
export type PendingSelection = { entity: string; id: string } | null;
export type ImportPreview = { ok?: boolean; row_count?: number; counts?: Record<string, number>; warnings?: string[]; errors?: Array<{ row: number; errors: string[] }> };
export type EntityRecord = { entity: string; record: CrmRecord };
export type CreatableEntity = 'lead' | 'account' | 'contact' | 'deal' | 'task' | 'note';
export type AccountBrief = { brief?: string; metrics?: Record<string, unknown>; risks?: string[]; opportunities?: string[]; next_actions?: IntelligentNextAction[] };
export type EnrichmentResult = { suggestions?: Array<{ field?: string; value?: unknown; confidence?: number; reason?: string }>; workflow_proposal?: { id?: string; title?: string } };
export type ExternalRef = {
  id: string;
  source_app_id?: string;
  source_entity_type?: string;
  source_entity_id?: string;
  link_type?: string;
  title?: string;
  summary?: string;
  occurred_at?: string;
  timestamp?: string;
};
export type SalesReportsPayload = {
  pipeline_value_by_stage?: Array<{ stage?: string; stage_id?: string; count?: number; total_value?: number; weighted_value?: number; currency?: string }>;
  weighted_forecast?: { total_value?: number; total_weighted_value?: number; by_currency?: Record<string, unknown> };
  deal_aging?: Array<{ id?: string; name?: string; stage?: string; age_days?: number; value?: number; currency?: string }>;
  lead_conversion?: { total?: number; converted?: number; conversion_rate?: number };
  task_overdue?: { total?: number; by_owner?: Array<{ owner_id?: string; count?: number }> };
  activities_by_owner?: Array<{ owner_id?: string; activity_type?: string; count?: number }>;
};
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
  counts: {},
  view_state: { view_filter: { mode: 'search', query: '', entity_type: 'all', refs: [], title: '' } }
};
