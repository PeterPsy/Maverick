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
  }>;
  surfaces?: {
    backend: boolean;
    cli_commands: string[];
    mcp_tools: string[];
  };
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

export function disableSecret(secretId: string): Promise<{ secret: SecretRecord }> {
  return request(`/api/secrets/${encodeURIComponent(secretId)}/disable`, { method: 'POST', body: '{}' });
}

export function revokeSecret(secretId: string): Promise<{ secret: SecretRecord }> {
  return request(`/api/secrets/${encodeURIComponent(secretId)}/revoke`, { method: 'POST', body: '{}' });
}

export function listGrants(): Promise<{ items: SecretGrant[] }> {
  return request('/api/secret-grants');
}

export function createGrant(payload: {
  app_id: string;
  logical_name: string;
  secret_id: string;
  actions: string[];
  target_patterns: string[];
  expires_at?: string;
  reason?: string;
}): Promise<{ grant: SecretGrant }> {
  return request('/api/secret-grants', { method: 'POST', body: JSON.stringify(payload) });
}

export function revokeGrant(grantId: string): Promise<{ grant: SecretGrant }> {
  return request(`/api/secret-grants/${encodeURIComponent(grantId)}/revoke`, { method: 'POST', body: '{}' });
}

export function listAudit(): Promise<{ items: AuditRecord[] }> {
  return request('/api/secret-audit');
}

export function listGrantTargets(): Promise<{ items: SecretGrantTarget[] }> {
  return request('/api/secret-grant-targets');
}

export function getProviderStatus(): Promise<ProviderStatus> {
  return request('/api/providers/active');
}
