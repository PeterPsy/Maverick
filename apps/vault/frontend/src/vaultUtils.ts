import { AuditRecord, SecretGrant, SecretRecord } from './api';
import { Tab } from './vaultTypes';

export function grantStatus(grant: SecretGrant): string {
  return grant.effective_status || grant.status;
}

export function buildTargetPatterns(form: FormData): string[] {
  const mode = String(form.get('target_mode') || 'app_backend_all');
  if (mode === 'app_backend') {
    return ['maverick://app.backend/backend'];
  }
  if (mode === 'app_cli') {
    const command = encodeTargetSegment(String(form.get('target_cli_command') || ''));
    return command ? [`maverick://app.backend/cli/${command}`] : [];
  }
  if (mode === 'app_mcp') {
    const tool = encodeTargetSegment(String(form.get('target_mcp_tool') || ''));
    return tool ? [`maverick://app.backend/mcp/${tool}`] : [];
  }
  if (mode === 'custom') {
    const custom = String(form.get('target_custom') || '').trim();
    return custom ? [custom] : [];
  }
  return ['maverick://app.backend/*'];
}

export function grantUsesSecret(grant: SecretGrant, secret: SecretRecord | undefined): boolean {
  if (!secret) {
    return false;
  }
  return grant.secret_ref === `platform:secrets/${secret.secret_id}` || (secret.alias ? grant.secret_ref === `platform:secret-alias/${secret.alias}` : false);
}

export function confirmSecretChange(secrets: SecretRecord[], grants: SecretGrant[], secretId: string, action: 'disable' | 'revoke'): boolean {
  const secret = secrets.find((item) => item.secret_id === secretId);
  const impacted = grants.filter((grant) => grantStatus(grant) === 'active' && grantUsesSecret(grant, secret)).length;
  const verb = action === 'disable' ? 'Disable' : 'Revoke';
  const effect = action === 'disable' ? 'The stored value remains encrypted, but linked active grants will be revoked.' : 'The stored value will be deleted and linked active grants will be revoked.';
  return window.confirm(`${verb} ${secret?.label || secretId}?\n\n${effect}\nImpacted active grants: ${impacted}`);
}

export function confirmGrantRevoke(grants: SecretGrant[], grantId: string): boolean {
  const grant = grants.find((item) => item.grant_id === grantId);
  return window.confirm(`Revoke grant ${grant?.logical_name || grantId} for ${grant?.app_id || 'this app'}?`);
}

export function toApiExpiry(value: string): string {
  if (!value) {
    return '';
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString();
}

export function tabFromSearchParams(): Tab {
  return tabFromValue(new URLSearchParams(window.location.search).get('tab')) || 'secrets';
}

export function tabFromValue(value: unknown): Tab | null {
  return value === 'readiness' || value === 'secrets' || value === 'grants' || value === 'audit' ? value : null;
}

export function humanizeKind(value: string) {
  return value.replace(/_/g, ' ');
}

export function secretMatchesQuery(secret: SecretRecord, query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return true;
  }
  return `${secret.label} ${secret.alias || ''} ${secret.secret_id} ${secret.kind} ${secret.status} ${secret.description || ''}`.toLowerCase().includes(needle);
}

export function grantMatchesQuery(grant: SecretGrant, query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return true;
  }
  return `${grant.app_id} ${grant.logical_name} ${grant.secret_ref} ${grant.actions.join(' ')} ${grant.target_patterns.join(' ')} ${grantStatus(grant)}`.toLowerCase().includes(needle);
}

export function auditMatchesQuery(item: AuditRecord, query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return true;
  }
  return `${item.action} ${item.status} ${item.detail} ${item.source_domain} ${item.app_id || ''}`.toLowerCase().includes(needle);
}

export function parseCsv(text: string): Array<Record<string, string>> {
  const rows: string[][] = [];
  let current = '';
  let row: string[] = [];
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (char === '"' && quoted && next === '"') {
      current += '"';
      index += 1;
      continue;
    }
    if (char === '"') {
      quoted = !quoted;
      continue;
    }
    if (char === ',' && !quoted) {
      row.push(current);
      current = '';
      continue;
    }
    if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && next === '\n') {
        index += 1;
      }
      row.push(current);
      if (row.some((cell) => cell.trim())) {
        rows.push(row);
      }
      row = [];
      current = '';
      continue;
    }
    current += char;
  }
  row.push(current);
  if (row.some((cell) => cell.trim())) {
    rows.push(row);
  }
  const [headers = [], ...records] = rows;
  const keys = headers.map((header) => header.trim().toLowerCase());
  return records.map((record) =>
    Object.fromEntries(keys.map((key, index) => [key, record[index]?.trim() || '']).filter(([key]) => key))
  );
}

function encodeTargetSegment(value: string): string {
  return value.trim().replace(/^\/+/, '').replace(/[?#]/g, '');
}
