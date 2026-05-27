import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { KeyRound, RotateCcw } from 'lucide-react';
import {
  SecretRecord,
  createSecret,
  listSecrets,
  rotateSecret,
  updateSecret
} from '../../api';
import { SecureSecretInput } from '../../components/SecureSecretInput';
import { CredentialPanel } from '../../vaultTypes';
import { notifyVaultDataChanged, notifyVaultViewStateChanged, readVaultActionRequest, readVaultViewState, writeVaultViewState } from '../../vaultViewState';
import '../widget-styles.css';

function VaultSidebarWidget() {
  const appId = currentVaultAppId();
  const [secrets, setSecrets] = useState<SecretRecord[]>([]);
  const [query, setQuery] = useState(() => readVaultViewState().query);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selectedSecretId, setSelectedSecretId] = useState(() => readVaultViewState().selectedSecretId);
  const [credentialPanel, setCredentialPanel] = useState<CredentialPanel>(() => readVaultViewState().credentialPanel);
  const lastActionRequestId = useRef('');
  const credentialFormRef = useRef<HTMLFormElement | null>(null);
  const credentialEditorFormRef = useRef<HTMLFormElement | null>(null);

  const activeSecrets = useMemo(() => secrets.filter((item) => item.status === 'active'), [secrets]);
  const selectedSecret = useMemo(() => activeSecrets.find((item) => item.secret_id === selectedSecretId) || null, [activeSecrets, selectedSecretId]);

  async function refresh() {
    try {
      const secretPayload = await listSecrets();
      setSecrets(secretPayload.items);
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load Vault.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    if (!selectedSecretId || activeSecrets.some((secret) => secret.secret_id === selectedSecretId)) {
      return;
    }
    setSelectedSecretId('');
    if (credentialPanel === 'edit') {
      setCredentialPanel('');
    }
  }, [activeSecrets, credentialPanel, selectedSecretId]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string };
      if (payload.type === 'maverick.widget.context-changed' || (payload.type === 'maverick.widget.data-changed' && payload.owner_app_id === appId)) {
        if (payload.resource === 'view-state') {
          const nextState = readVaultViewState();
          setCredentialPanel(nextState.credentialPanel);
          setQuery(nextState.query);
          setSelectedSecretId(nextState.selectedSecretId);
        }
        if (payload.resource === 'action-request') {
          runRequestedAction();
        }
        void refresh();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId]);

  function runRequestedAction() {
    const request = readVaultActionRequest();
    if (!request || request.id === lastActionRequestId.current) {
      return;
    }
    lastActionRequestId.current = request.id;
    if (request.action === 'new-credential') {
      openNewCredentialPanel();
    }
    if (request.action === 'rotate-credential') {
      window.setTimeout(() => credentialEditorFormRef.current?.requestSubmit(), 0);
    }
  }

  function openNewCredentialPanel() {
    setCredentialPanel('new');
    setSelectedSecretId('');
    writeVaultViewState({ ...readVaultViewState(), credentialPanel: 'new', query, selectedSecretId: '' });
    notifyVaultViewStateChanged();
  }

  async function submit(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
      await refresh();
      notifyVaultDataChanged();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Vault request failed.');
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const rawValue = String(form.get('raw_value') || '');
    formElement.reset();
    await submit(async () => {
      const payload = await createSecret({
        label: String(form.get('label') || ''),
        alias: String(form.get('alias') || '') || undefined,
        description: String(form.get('description') || '') || undefined,
        raw_value: rawValue,
        kind: String(form.get('kind') || 'generic')
      });
      setSelectedSecretId(payload.secret.secret_id);
      setCredentialPanel('edit');
      writeVaultViewState({ credentialPanel: 'edit', metricFilter: null, query, selectedSecretId: payload.secret.secret_id, tab: 'credentials' });
      notifyVaultViewStateChanged();
    });
  }

  async function handleRotateCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const secretId = String(form.get('secret_id') || '');
    const rawValue = String(form.get('raw_value') || '');
    const rawInput = formElement.elements.namedItem('raw_value') as HTMLInputElement | null;
    await submit(async () => {
      await updateSecret(secretId, {
        label: String(form.get('label') || ''),
        alias: String(form.get('alias') || '') || undefined,
        description: String(form.get('description') || '') || undefined,
        kind: String(form.get('kind') || 'generic')
      });
      if (rawValue) {
        await rotateSecret(secretId, rawValue);
      }
    });
    if (rawInput) {
      rawInput.value = '';
    }
  }

  return (
    <main className="vault-sidebar-widget" aria-busy={busy}>
      <section className="vault-sidebar-list">
        {credentialPanel === 'new' ? (
          <div className="vault-sidebar-form-stack">
            <form className="vault-sidebar-form" onSubmit={handleCreateCredential} ref={credentialFormRef}>
              <p className="vault-sidebar-section-title"><KeyRound size={14} aria-hidden="true" />New credential</p>
              <input aria-label="Credential title" name="label" placeholder="Title" required />
              <SecureSecretInput label="Key" placeholder="Paste key or password" />
              <details className="vault-sidebar-optional-fields">
                <summary>Optional</summary>
                <div className="vault-sidebar-optional-body">
                  <input aria-label="Credential alias" name="alias" placeholder="alias-name" />
                  <select aria-label="Credential type" name="kind" defaultValue="generic">
                    <option value="generic">Generic</option>
                    <option value="password">Password</option>
                    <option value="api_key">API key</option>
                    <option value="oauth_token">OAuth token</option>
                    <option value="private_key">Private key</option>
                  </select>
                  <textarea aria-label="Credential description" name="description" placeholder="Description" rows={3} />
                </div>
              </details>
              <button className="vault-sidebar-submit" type="submit">Create credential</button>
            </form>
          </div>
        ) : null}

        {credentialPanel !== 'new' ? (
          <div className="vault-sidebar-form-stack">
            <form className="vault-sidebar-form" onSubmit={handleRotateCredential} ref={credentialEditorFormRef}>
              <p className="vault-sidebar-section-title"><RotateCcw size={14} aria-hidden="true" />Edit credential</p>
              <input name="secret_id" type="hidden" value={selectedSecretId} />
              {selectedSecret ? (
                <div className="vault-sidebar-edit-fields" key={selectedSecret.secret_id}>
                  <input aria-label="Credential title" defaultValue={selectedSecret.label} name="label" placeholder="Title" required />
                  <input aria-label="Credential alias" defaultValue={selectedSecret.alias || ''} name="alias" placeholder="alias-name" />
                  <select aria-label="Credential type" defaultValue={selectedSecret.kind} name="kind">
                    <option value="generic">Generic</option>
                    <option value="password">Password</option>
                    <option value="api_key">API key</option>
                    <option value="oauth_token">OAuth token</option>
                    <option value="private_key">Private key</option>
                  </select>
                  <textarea aria-label="Credential description" defaultValue={selectedSecret.description || ''} name="description" placeholder="Description" rows={3} />
                  <label className="vault-redacted-input">
                    <span>Current key</span>
                    <input aria-label="Current key" disabled readOnly type="password" value="••••••••••••" />
                  </label>
                  <SecureSecretInput label="New key" placeholder="Paste new key to rotate" required={false} />
                  <button className="vault-sidebar-submit" type="submit">Save changes</button>
                </div>
              ) : (
                <div className="vault-sidebar-status">Select a credential in Active Credentials to edit details or rotate its key.</div>
              )}
            </form>
          </div>
        ) : null}

        {error ? <p className="vault-sidebar-status">{error}</p> : null}
        {loading && !error ? <p className="vault-sidebar-status">Loading Vault metadata...</p> : null}
      </section>
    </main>
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

createRoot(document.getElementById('vault-sidebar-root') as HTMLElement).render(<VaultSidebarWidget />);
