import { AuditRecord, SecretGrant, SecretRecord } from './api';
import { Tab } from './vaultTypes';

export function grantStatus(grant: SecretGrant): string {
  return grant.effective_status || grant.status;
}

export function grantResourceScopeLabel(grant: SecretGrant): string {
  if (grant.resource_type && grant.resource_id) {
    return `${grant.resource_type}:${grant.resource_id}`;
  }
  return 'workspace';
}

export function grantUsesSecret(grant: SecretGrant, secret: SecretRecord | undefined): boolean {
  if (!secret) {
    return false;
  }
  return grant.secret_ref === `platform:secrets/${secret.secret_id}` || (secret.alias ? grant.secret_ref === `platform:secret-alias/${secret.alias}` : false);
}

export function toApiExpiry(value: string): string {
  if (!value) {
    return '';
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString();
}

export function tabFromSearchParams(): Tab {
  return tabFromValue(new URLSearchParams(window.location.search).get('tab')) || 'credentials';
}

export function tabFromValue(value: unknown): Tab | null {
  if (value === 'credentials' || value === 'issues' || value === 'import' || value === 'advanced') {
    return value;
  }
  if (value === 'secrets') {
    return 'credentials';
  }
  if (value === 'readiness') {
    return 'issues';
  }
  if (value === 'grants' || value === 'audit') {
    return 'advanced';
  }
  return null;
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
  return `${grant.app_id} ${grant.logical_name} ${grant.secret_ref} ${grant.actions.join(' ')} ${grant.target_patterns.join(' ')} ${grantResourceScopeLabel(grant)} ${grantStatus(grant)}`.toLowerCase().includes(needle);
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
