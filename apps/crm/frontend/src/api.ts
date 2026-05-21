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
  name: string;
  position: number;
  probability: number;
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
  accounts: CrmRecord[];
  contacts: CrmRecord[];
  deals: CrmRecord[];
  tasks: CrmRecord[];
  notes: CrmRecord[];
  activities: CrmRecord[];
  pipeline_stages: PipelineStage[];
  counts: Record<string, number>;
  view_state: CrmViewState;
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
