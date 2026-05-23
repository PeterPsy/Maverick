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
