import { ChangeEvent, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Plus, Upload } from 'lucide-react';
import { createSecret } from '../../api';
import { Tab } from '../../vaultTypes';
import { parseCsv } from '../../vaultUtils';
import { notifyVaultDataChanged, notifyVaultViewStateChanged, readVaultViewState, writeVaultActionRequest, writeVaultViewState } from '../../vaultViewState';
import '../widget-styles.css';

const WIDGET_ID = 'vault-sidebar-footer';
const MAX_CSV_BYTES = 512 * 1024;
const MAX_IMPORT_ROWS = 100;

function VaultSidebarFooterWidget() {
  const appId = currentVaultAppId();
  const [tab, setTab] = useState<Tab>(() => readVaultViewState().tab);
  const [importing, setImporting] = useState(false);
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
      window.alert('CSV import is limited to 512 KB.');
      return;
    }
    setImporting(true);
    try {
      const rows = parseCsv(await file.text());
      const secretRows = rows.filter((row) => row.password || row.value || row.raw_value);
      if (!secretRows.length) {
        window.alert('No importable secret rows were found.');
        return;
      }
      if (secretRows.length > MAX_IMPORT_ROWS) {
        window.alert(`CSV import is limited to ${MAX_IMPORT_ROWS} secret rows. This file has ${secretRows.length}.`);
        return;
      }
      const confirmed = window.confirm(`Import ${secretRows.length} secrets from ${file.name}? Values will be stored in Core Secrets and will not be shown again after import.`);
      if (!confirmed) {
        return;
      }
      let created = 0;
      const failures: string[] = [];
      for (const [index, row] of secretRows.entries()) {
        const password = row.password || row.value || row.raw_value || '';
        const name = row.name || row.title || row.url || row.origin || 'Imported secret';
        const username = row.username || row.user || row.login || '';
        const url = row.url || row.origin || '';
        try {
          await createSecret({
            label: username ? `${name} (${username})` : name,
            description: ['Imported from CSV', url ? `source: ${url}` : '', username ? `user: ${username}` : ''].filter(Boolean).join('\n'),
            kind: 'password',
            raw_value: password
          });
          created += 1;
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Unable to create secret.';
          failures.push(`row ${index + 2}: ${message}`);
        }
      }
      if (created) {
        writeVaultViewState({ ...readVaultViewState(), metricFilter: null, tab: 'secrets' });
        notifyVaultDataChanged();
        notifyVaultViewStateChanged();
        window.parent?.postMessage({ type: 'maverick.widget.open-app', app_id: appId, params: { tab: 'secrets' } }, window.location.origin);
      }
      const failureSummary = failures.length ? `\n\nFailures:\n${failures.slice(0, 5).join('\n')}${failures.length > 5 ? `\n...and ${failures.length - 5} more.` : ''}` : '';
      window.alert(`Imported ${created} of ${secretRows.length} secrets.${failureSummary}`);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : 'Unable to import CSV.');
    } finally {
      setImporting(false);
    }
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
    </main>
  );
}

function runPrimaryAction(appId: string, tab: Tab) {
  const action = primaryActionFor(tab);
  writeVaultViewState({ ...readVaultViewState(), metricFilter: null, tab });
  notifyVaultViewStateChanged();
  if (tab === 'secrets') {
    writeVaultActionRequest('submit-secret');
    return;
  }
  if (tab === 'grants') {
    writeVaultActionRequest('submit-grant');
    return;
  }
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: appId,
      params: action.params
    },
    window.location.origin
  );
}

function primaryActionFor(tab: Tab): { label: string; params: Record<string, string> } {
  if (tab === 'grants') {
    return { label: 'New grant', params: { focus: 'new-grant', tab: 'grants' } };
  }
  if (tab === 'audit') {
    return { label: 'View audit', params: { tab: 'audit' } };
  }
  return { label: 'New secret', params: { focus: 'new-secret', tab: 'secrets' } };
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
    window.location.origin
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
