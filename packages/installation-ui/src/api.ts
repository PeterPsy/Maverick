export type Requirement = { id: string; label: string; kind: string; url: string; provider_url?: string; configured?: boolean };
export type Configuration = { hostname: string; public_url: string; target_ip: string; generation: number; managed: boolean };
export type Verification = { healthy: boolean; checks: { host: string; healthy: boolean; error?: string; status?: number }[] };
export type Job = { job_id: string; plan_id: string; status: string; step: string; error_code?: string; retry_at?: string; confirmed_actions?: string[]; verification?: Verification };
export type Plan = { plan_id: string; hostname: string; target_ip: string; public_url: string; certificate_names: string[];
  dns_changes: { name: string; action: string; after?: { type: string; content: string } }[];
  blocking_issues: { code: string; nameservers?: string[] }[]; external_actions: Requirement[]; requirements: Requirement[]; token_template_url?: string };
export type Inspection = { configuration: Configuration; dns_credentials: { label: string; ref: string }[]; configured: boolean;
  requirements: Requirement[]; latest_job?: Job; worker?: { state: string; public_ip?: string; checked_at?: string; renewal_state?: string; verification?: Verification } };
export const terminalJob = (job: Job) => ['ready', 'rolled_back', 'failed', 'rollback_requested'].includes(job.status);

export class InstallationApiError extends Error {
  constructor(public code: string, public status: number) { super(code); }
}

export async function installationRequest<T>(operation: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch('/api/admin/installation' + (operation === 'inspect' ? '' : '/' + operation), {
    method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal,
    headers: { 'Accept': 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const payload = await response.json();
  if (!response.ok) throw new InstallationApiError(payload.error || 'installation_operation_failed', response.status);
  return payload as T;
}

export async function saveDnsCredential(rawValue: string, signal?: AbortSignal): Promise<string> {
  if (!window.isSecureContext) throw new InstallationApiError('secure_connection_required', 400);
  const response = await fetch('/api/secrets', {
    method: 'POST', credentials: 'same-origin', signal, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label: 'Cloudflare DNS', kind: 'api_key', alias: 'cloudflare-dns-' + crypto.randomUUID().slice(0, 8), raw_value: rawValue }),
  });
  const payload = await response.json();
  if (!response.ok) throw new InstallationApiError(payload.error || 'credential_save_failed', response.status);
  return 'platform:secrets/' + payload.secret.secret_id;
}
