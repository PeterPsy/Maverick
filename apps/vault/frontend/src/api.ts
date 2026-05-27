export type SecretRecord = {
  secret_id: string;
  alias: string | null;
  label: string;
  description: string | null;
  status: 'active' | 'disabled' | 'revoked';
  kind: string;
  created_at: string;
  updated_at: string;
};

export type SecretGrant = {
  grant_id: string;
  workspace_id: string;
  app_id: string;
  secret_ref: string;
  logical_name: string;
  actions: string[];
  target_patterns: string[];
  status: 'active' | 'revoked';
  effective_status?: 'active' | 'revoked' | 'blocked' | 'orphaned' | 'expired';
  linked_secret_status?: 'active' | 'disabled' | 'revoked' | 'missing';
  resource_type: string | null;
  resource_id: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
  created_by_user_id: string | null;
  reason: string | null;
};

export type SecretGrantTarget = {
  app_id: string;
  public_app_id?: string;
  mount_app_id?: string;
  name: string;
  status: string;
  logical_names: string[];
  consumers?: Record<string, {
    backend: boolean;
    cli_commands: string[];
    mcp_tools: string[];
    resource_scoped?: boolean;
    resource_types?: string[];
  }>;
  surfaces?: {
    backend: boolean;
    cli_commands: string[];
    mcp_tools: string[];
  };
};

export type SecretGrantNeed = {
  app_id: string;
  app_name: string;
  logical_name: string;
  human_label?: string;
  scope?: {
    type?: string;
    label?: string;
    resource_type?: string | null;
    resource_id?: string | null;
  };
  recommended_grant?: {
    actions?: string[];
    target_patterns?: string[];
    resource_type?: string | null;
    resource_id?: string | null;
    reason?: string;
  };
  value_state: string;
  grant_state: string;
  user_action: string;
  credential_match?: {
    matched?: boolean;
    method?: string;
    confidence?: string;
    ambiguous?: boolean;
    candidate_count?: number;
    candidates?: Array<{
      secret_id?: string;
      alias?: string | null;
      label?: string;
      status?: string;
      kind?: string;
    }>;
  };
  app_managed?: boolean;
};

export type ProviderDefinition = {
  provider_id: string;
  label: string;
  status: string;
  requires_credentials: boolean;
};

export type ProviderSelection = {
  workspace_id: string;
  provider_id: string;
  binding_id: string | null;
};

export type ProviderStatus = {
  workspace_id: string;
  configured: boolean;
  active_provider: ProviderDefinition | null;
  selection: ProviderSelection | null;
  blocked_reason: string | null;
  blocked_detail?: string | null;
  available_providers: ProviderDefinition[];
};

export type AuditRecord = {
  audit_id: string;
  action: string;
  status: 'attempted' | 'succeeded' | 'failed';
  source_domain: string;
  workspace_id: string | null;
  app_id: string | null;
  runtime_session_id: string | null;
  provider_id: string | null;
  detail: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}) },
    ...init
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : payload.error || response.statusText;
    throw new Error(String(detail));
  }
  return payload as T;
}

export function listSecrets(): Promise<{ items: SecretRecord[] }> {
  return request('/api/secrets');
}

export function createSecret(payload: {
  label: string;
  raw_value: string;
  alias?: string;
  description?: string;
  kind?: string;
}): Promise<{ secret: SecretRecord }> {
  return request('/api/secrets', { method: 'POST', body: JSON.stringify(payload) });
}

export function rotateSecret(secretId: string, rawValue: string): Promise<{ secret: SecretRecord }> {
  return request(`/api/secrets/${encodeURIComponent(secretId)}/rotate`, {
    method: 'POST',
    body: JSON.stringify({ raw_value: rawValue })
  });
}

export function updateSecret(secretId: string, payload: {
  alias?: string;
  description?: string;
  kind: string;
  label: string;
}): Promise<{ secret: SecretRecord }> {
  return request(`/api/secrets/${encodeURIComponent(secretId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  });
}

export function listGrants(): Promise<{ items: SecretGrant[] }> {
  return request('/api/secret-grants');
}

export function listAudit(): Promise<{ items: AuditRecord[] }> {
  return request('/api/secret-audit');
}

export function listGrantTargets(): Promise<{ items: SecretGrantTarget[]; needs?: SecretGrantNeed[] }> {
  return request('/api/secret-grant-targets');
}

export function listGrantNeeds(): Promise<{ items: SecretGrantNeed[] }> {
  return request('/api/secret-grant-needs');
}

export function getProviderStatus(): Promise<ProviderStatus> {
  return request('/api/providers/active');
}
