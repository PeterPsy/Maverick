import { ChangeEvent, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Download, Plus, Upload, X } from 'lucide-react';
import { SecretRecord, createSecret, listSecrets } from '../../api';
import { Tab } from '../../vaultTypes';
import { parseCsv } from '../../vaultUtils';
import { notifyVaultDataChanged, notifyVaultViewStateChanged, readVaultViewState, writeVaultActionRequest, writeVaultViewState } from '../../vaultViewState';
import '../widget-styles.css';

const WIDGET_ID = 'vault-sidebar-footer';
const MAX_CSV_BYTES = 512 * 1024;
const MAX_IMPORT_ROWS = 100;
const SECRET_ID_PATTERN = /^[a-z0-9][a-z0-9._-]{1,126}$/;

type ImportRow = {
  description: string;
  issue: string;
  label: string;
  raw_value: string;
  secret_id: string;
  selected: boolean;
  status: 'will_create' | 'will_fail';
};

type ImportPreview = {
  batchId: string;
  fileName: string;
  rows: ImportRow[];
};

function VaultSidebarFooterWidget() {
  const appId = currentVaultAppId();
  const [tab, setTab] = useState<Tab>(() => readVaultViewState().tab);
  const [importing, setImporting] = useState(false);
  const [importKind, setImportKind] = useState('password');
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [importStatus, setImportStatus] = useState('');
  const [importFailures, setImportFailures] = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const action = primaryActionFor(tab);

  useEffect(() => {
    postPrimaryActionState(appId, action.label);
  }, [action.label, appId]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string; widget_id?: string };
      if (payload.owner_app_id !== appId || payload.widget_id !== WIDGET_ID) {
        if (payload.type === 'maverick.widget.data-changed' && payload.owner_app_id === appId && payload.resource === 'view-state') {
          setTab(readVaultViewState().tab);
        }
        return;
      }
      if (payload.type === 'maverick.widget.primary-action.query') {
        postPrimaryActionState(appId, primaryActionFor(readVaultViewState().tab).label);
      }
      if (payload.type === 'maverick.widget.primary-action.invoke') {
        runPrimaryAction(appId, readVaultViewState().tab);
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId]);

  async function importCsv(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = '';
    if (!file) {
      return;
    }
    if (file.size > MAX_CSV_BYTES) {
      setImportStatus('CSV import is limited to 512 KB.');
      return;
    }
    setImporting(true);
    try {
      const rows = parseCsv(await file.text());
      const secretRows = buildImportRows(rows);
      if (!secretRows.length) {
        setImportStatus('No importable secret rows were found.');
        return;
      }
      if (secretRows.length > MAX_IMPORT_ROWS) {
        setImportStatus(`CSV import is limited to ${MAX_IMPORT_ROWS} secret rows. This file has ${secretRows.length}.`);
        return;
      }
      const secretPayload = await listSecrets();
      const previewRows = preflightImportRows(secretRows, secretPayload.items);
      setImportFailures([]);
      setImportStatus('');
      setImportPreview({ batchId: newBatchId(), fileName: file.name, rows: previewRows });
    } catch (error) {
      setImportStatus(error instanceof Error ? error.message : 'Unable to import CSV.');
    } finally {
      setImporting(false);
    }
  }

  async function commitImport() {
    if (!importPreview) {
      return;
    }
    setImporting(true);
    setImportStatus('');
    const failures: string[] = [];
    let created = 0;
    const rowsToCreate = importPreview.rows.filter((row) => row.selected && row.status === 'will_create');
    for (const [index, row] of rowsToCreate.entries()) {
      try {
        await createSecret({
          label: row.label,
          description: [row.description, `batch: ${importPreview.batchId}`].filter(Boolean).join('\n'),
          kind: importKind,
          raw_value: row.raw_value
        });
        created += 1;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unable to create secret.';
        failures.push(`row ${index + 1}: ${message}`);
      }
    }
    if (created) {
      writeVaultViewState({ ...readVaultViewState(), credentialPanel: '', metricFilter: null, selectedSecretId: '', tab: 'credentials' });
      notifyVaultDataChanged();
      notifyVaultViewStateChanged();
      window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: appId, params: { tab: 'credentials' } }, "*");
    }
    setImportFailures(failures);
    setImportStatus(`Imported ${created} of ${rowsToCreate.length} selected secrets.`);
    setImportPreview(null);
    setImporting(false);
  }

  function toggleImportRow(rowIndex: number) {
    setImportPreview((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        rows: current.rows.map((row, index) => index === rowIndex ? { ...row, selected: !row.selected } : row)
      };
    });
  }

  return (
    <main className="vault-sidebar-footer-widget">
      <button className="vault-sidebar-footer-button" onClick={() => runPrimaryAction(appId, tab)} type="button">
        <Plus size={16} aria-hidden="true" />
        <span>{action.label}</span>
      </button>
      <button className="vault-sidebar-upload-button" disabled={importing} onClick={() => fileInputRef.current?.click()} title="Import secrets from CSV" type="button">
        <Upload size={16} aria-hidden="true" />
      </button>
      <input ref={fileInputRef} accept=".csv,text/csv" className="vault-sidebar-file-input" onChange={importCsv} type="file" />
      {importPreview ? (
        <section className="vault-import-popover" aria-label="CSV import preview">
          <div className="vault-import-popover__header">
            <strong>{importPreview.rows.length} secrets</strong>
            <button onClick={() => setImportPreview(null)} title="Cancel import" type="button"><X size={15} /></button>
          </div>
          <span>{importPreview.fileName} · {importPreview.batchId}</span>
          <select aria-label="Secret kind" onChange={(event) => setImportKind(event.currentTarget.value)} value={importKind}>
            <option value="password">Password</option>
            <option value="api_key">API key</option>
            <option value="oauth_token">OAuth token</option>
            <option value="generic">Generic</option>
          </select>
          <p>{importPreview.rows.filter((row) => row.status === 'will_create' && row.selected).length} selected · {importPreview.rows.filter((row) => row.status === 'will_fail').length} will fail</p>
          <div className="vault-import-rows" role="list">
            {importPreview.rows.map((row, index) => (
              <label className="vault-import-row" key={`${row.secret_id}:${index}`} role="listitem">
                <input
                  checked={row.selected}
                  disabled={row.status === 'will_fail'}
                  onChange={() => toggleImportRow(index)}
                  type="checkbox"
                />
                <span>
                  <strong>{row.label}</strong>
                  <small>{row.status === 'will_create' ? 'will create' : `will fail: ${row.issue}`}</small>
                </span>
              </label>
            ))}
          </div>
          <button disabled={importing || !importPreview.rows.some((row) => row.selected && row.status === 'will_create')} onClick={commitImport} type="button">Import selected</button>
        </section>
      ) : null}
      {importStatus ? <p className="vault-import-status">{importStatus}</p> : null}
      {importFailures.length ? (
        <button className="vault-sidebar-upload-button" onClick={() => downloadFailures(importFailures)} title="Download import errors" type="button">
          <Download size={16} aria-hidden="true" />
        </button>
      ) : null}
    </main>
  );
}

function buildImportRows(rows: Array<Record<string, string>>): ImportRow[] {
  return rows
    .filter((row) => row.password || row.value || row.raw_value)
    .map((row) => {
      const rawValue = row.password || row.value || row.raw_value || '';
      const name = row.name || row.title || row.url || row.origin || 'Imported secret';
      const username = row.username || row.user || row.login || '';
      const url = row.url || row.origin || '';
      const label = username ? `${name} (${username})` : name;
      return {
        description: ['Imported from CSV', url ? `source: ${url}` : '', username ? `user: ${username}` : ''].filter(Boolean).join('\n'),
        label,
        raw_value: rawValue,
        secret_id: normalizeSecretId(label),
        issue: '',
        selected: true,
        status: 'will_create'
      };
    });
}

function preflightImportRows(rows: ImportRow[], secrets: SecretRecord[]): ImportRow[] {
  const existingNames = new Set<string>();
  for (const secret of secrets) {
    existingNames.add(secret.secret_id.toLowerCase());
    if (secret.alias) {
      existingNames.add(secret.alias.toLowerCase());
    }
  }
  const fileNames = new Map<string, number>();
  for (const row of rows) {
    fileNames.set(row.secret_id, (fileNames.get(row.secret_id) || 0) + 1);
  }
  return rows.map((row) => {
    const issue = !SECRET_ID_PATTERN.test(row.secret_id) ? 'normalized secret id is invalid'
      : existingNames.has(row.secret_id) ? 'secret id or alias already exists'
        : (fileNames.get(row.secret_id) || 0) > 1 ? 'duplicate normalized id in this file'
          : '';
    return { ...row, issue, selected: !issue, status: issue ? 'will_fail' : 'will_create' };
  });
}

function normalizeSecretId(value: string): string {
  const normalized = value.normalize('NFKD').replace(/[\u0300-\u036f]/g, '');
  const slug = normalized.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return slug || 'secret';
}

function newBatchId() {
  const suffix = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID().slice(0, 8) : String(Date.now()).slice(-8);
  return `vault-import-${new Date().toISOString().slice(0, 10)}-${suffix}`;
}

function downloadFailures(failures: string[]) {
  const blob = new Blob([failures.join('\n')], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `vault-import-errors-${new Date().toISOString().slice(0, 10)}.txt`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function runPrimaryAction(_appId: string, _tab: Tab) {
  const currentState = readVaultViewState();
  writeVaultViewState({ ...currentState, credentialPanel: 'new', metricFilter: null, selectedSecretId: '' });
  notifyVaultViewStateChanged();
  writeVaultActionRequest('new-credential');
  window.parent?.postMessage({ type: 'maverick.shell.sidebar.open' }, "*");
}

function primaryActionFor(_tab: Tab): { label: string; params: Record<string, string> } {
  return { label: 'New credential', params: { focus: 'new-credential' } };
}

function postPrimaryActionState(appId: string, label: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.primary-action.state',
      owner_app_id: appId,
      widget_id: WIDGET_ID,
      available: true,
      label,
      preferred_surface: 'sidebar'
    },
    "*"
  );
}

function currentVaultAppId(pathname = typeof window === 'undefined' ? '' : window.location.pathname): string {
  const match = /^\/api\/apps\/widgets\/([^/?#]+)/.exec(pathname) || /^\/apps\/([^/?#]+)/.exec(pathname);
  if (!match?.[1]) {
    return 'vault';
  }
  try {
    return decodeURIComponent(match[1]) || 'vault';
  } catch {
    return match[1] || 'vault';
  }
}

createRoot(document.getElementById('vault-sidebar-footer-root') as HTMLElement).render(<VaultSidebarFooterWidget />);
