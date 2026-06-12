export type CrmRecord = {
  id: string;
  name?: string;
  display_name?: string;
  email?: string;
  domain?: string;
  account_id?: string;
  contact_id?: string;
  stage_id?: string;
  stage?: string;
  value?: number;
  currency?: string;
  probability?: number;
  close_date?: string;
  subject?: string;
  title?: string;
  body?: string;
  status?: string;
  summary?: string;
  updated_at?: string;
  [key: string]: unknown;
};

export type PipelineStage = {
  id: string;
  pipeline_id?: string;
  name: string;
  position: number;
  probability: number;
};

export type Pipeline = {
  id: string;
  name: string;
  is_default?: number;
};

export type PipelineBoardDeal = CrmRecord & {
  account_label?: string;
  contact_label?: string;
  age_days?: number | null;
  stuck_days?: number | null;
  health?: {
    status?: string;
    label?: string;
    age_days?: number | null;
    stuck_days?: number | null;
    is_stuck?: boolean;
    past_due?: boolean;
  };
  connection_summary?: {
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
    badges?: Array<{ key?: string; kind?: string; label?: string; count?: number; date?: string }>;
  };
};

export type PipelineBoardStage = PipelineStage & {
  deals?: PipelineBoardDeal[];
  deal_count?: number;
  totals?: Record<string, number>;
  weighted?: Record<string, number>;
  total_value?: number;
  weighted_value?: number;
};

export type PipelineBoardPayload = {
  ok: boolean;
  pipeline?: Pipeline;
  stages?: PipelineBoardStage[];
  totals?: {
    deal_count?: number;
    currency_totals?: Record<string, number>;
    weighted_currency_totals?: Record<string, number>;
    total_value?: number;
    weighted_value?: number;
  };
};

export type SavedView = {
  id: string;
  title: string;
  entity_type: string;
  query?: string;
  filters?: Record<string, unknown>;
  refs?: CrmViewRef[];
};

export type DuplicateGroup = {
  entity_type: string;
  field: string;
  value: string;
  count: number;
  records: CrmRecord[];
};

export type CustomFieldDefinition = {
  id: string;
  entity_type: string;
  field_key: string;
  label: string;
  field_type: string;
  required?: boolean;
  options?: string[];
};

export type IntelligentNextAction = {
  kind: string;
  score: number;
  reason: string;
  entity_type: string;
  entity_id: string;
  title: string;
  action?: Record<string, unknown>;
  record?: CrmRecord;
};

export type WorkflowProposal = {
  id: string;
  proposal_type?: string;
  status: 'pending' | 'approved' | 'applied' | 'dismissed' | 'rejected';
  entity_type: string;
  entity_id: string;
  title: string;
  proposal?: {
    action?: Record<string, unknown>;
    [key: string]: unknown;
  };
  source?: string;
  created_at?: string;
  updated_at?: string;
  approved_at?: string;
  applied_at?: string;
};

export type WorkflowProposalPreview = {
  proposal_id: string;
  status: string;
  action_type: string;
  target: {
    entity_type?: string;
    id?: string;
  };
  changes: Array<{
    field: string;
    current_value?: unknown;
    proposed_value?: unknown;
  }>;
  proposed_task?: Record<string, unknown> | null;
  validation_issues: string[];
  can_approve?: boolean;
  can_apply?: boolean;
};

export type WorkflowProposalPreviewPayload = {
  ok: boolean;
  workflow_proposal: WorkflowProposal;
  preview: WorkflowProposalPreview;
};

export type OperationsFeedItem = {
  kind: string;
  ref?: {
    entity_type?: string;
    entity_id?: string;
    proposal_id?: string;
    event_id?: string;
  };
  status?: string;
  title?: string;
  reason?: string;
  source?: string;
  evidence?: string[];
  action_type?: string;
  action?: Record<string, unknown>;
  priority?: string;
  score?: number;
  due_at?: string;
  created_at?: string;
  updated_at?: string;
  approved_at?: string;
  applied_at?: string;
};

export type OperationsFeedSection = {
  key: string;
  title?: string;
  count?: number;
  items?: OperationsFeedItem[];
};

export type OperationsFeedPayload = {
  ok: boolean;
  generated_at?: string;
  limit?: number;
  counts?: Record<string, number>;
  sections?: OperationsFeedSection[];
};

export type CrmViewRef = {
  entity_type?: string;
  entity_id?: string;
  id?: string;
};

export type CrmViewState = {
  view_filter?: {
    mode?: string;
    query?: string;
    entity_type?: string;
    refs?: CrmViewRef[];
    title?: string;
  };
};

export type BootstrapPayload = {
  ok: boolean;
  leads: CrmRecord[];
  accounts: CrmRecord[];
  contacts: CrmRecord[];
  deals: CrmRecord[];
  tasks: CrmRecord[];
  notes: CrmRecord[];
  activities: CrmRecord[];
  pipelines?: Pipeline[];
  pipeline_stages: PipelineStage[];
  saved_views?: SavedView[];
  duplicates?: { ok?: boolean; groups?: DuplicateGroup[] };
  schema?: { custom_fields?: CustomFieldDefinition[] };
  next_action_suggestions?: IntelligentNextAction[];
  workflow_proposals?: WorkflowProposal[];
  counts: Record<string, number>;
  view_state: CrmViewState;
};

export type RecordsTableColumn = {
  key: string;
  label: string;
};

export type RecordsTableRow = {
  entity_type: string;
  id: string;
  title: string;
  record: CrmRecord;
  computed?: Record<string, unknown>;
  display?: Record<string, string>;
  ref?: {
    entity_type?: string;
    entity_id?: string;
    app_page?: string;
  };
};

export type RecordsTablePayload = {
  ok: boolean;
  records: RecordsTableRow[];
  columns: RecordsTableColumn[];
  counts: Record<string, number>;
  next_cursor: string;
  has_more: boolean;
};

export async function callBackend<T = Record<string, unknown>>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/crm/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof payload.message === 'string' ? payload.message : `Backend request failed with ${response.status}`;
    throw new Error(message);
  }
  return payload as T;
}
