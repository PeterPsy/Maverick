import { readMaverickAppFrameContext } from '@maverick/pwa-cache';

export type Release = { release_id: string; digest: string; source_revision?: string; size_bytes?: number; file_count?: number; format: string };
export type Plan = { id: string; app_id: string; kind: string; status: string; hostname: string; source_revision: string; plan_digest: string; expires: number; release?: Release; approved_by?: string; error_code?: string; risk_summary: string; will_replace_release_id?: string };
export type Publication = { id: string; name: string; source_id: string; provider_id: string; managed_url: string; status: string; last_error_code: string; health: { status: string; checked_at?: number }; binding: { generation: number; current?: Release; previous?: Release; enabled: boolean; archived: boolean } };
export type Detail = { app: Publication; plans: Plan[]; releases: Release[]; history: { created: number; action: string; actor: string; detail: string }[] };
export const appId = readMaverickAppFrameContext()?.appId || /^\/apps\/([^/]+)/.exec(window.location.pathname)?.[1] || 'external-apps';

export async function callBackend<T>(body: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/apps/${encodeURIComponent(appId)}/backend`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  });
  const result = await response.json();
  if (!response.ok || result.error_code || result.status === 'failed') throw new Error(result.error_code === 'public_tls_not_ready' ? 'Certificato HTTPS in preparazione. Attendi un minuto e riprova: il piano non è stato consumato.' : result.error_code || `HTTP ${response.status}`);
  return result as T;
}

export const labels: Record<string, string> = { draft: 'Bozza', published: 'Pubblicata', suspended: 'Sospesa', archived: 'Archiviata', healthy: 'Verificata', degraded: 'Verifica fallita', unknown: 'Da verificare', ready: 'Da approvare', preparing: 'Preparazione', applied: 'Applicato', failed: 'Fallito' };
export function label(value: string) { return labels[value] || value; }
export function date(value?: number) { return value ? new Date(value * 1000).toLocaleString() : '—'; }

export async function copyPublicUrl(value: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(value); return true; }
  catch {
    // Isolated non-Chat frames do not receive clipboard-write delegation.
    // Keep an explicit-click fallback without asking Core for broader authority.
    const focused = document.activeElement as HTMLElement | null;
    const field = document.createElement('textarea');
    field.value = value; field.readOnly = true; field.style.position = 'fixed'; field.style.opacity = '0';
    document.body.append(field); field.select();
    try { return document.execCommand('copy'); }
    catch { return false; }
    finally { field.remove(); focused?.focus(); }
  }
}
