import { CredentialPanel, Tab } from './vaultTypes';
import { tabFromValue } from './vaultUtils';

export const VAULT_VIEW_STATE_KEY = 'maverick.vault.viewState';
export const VAULT_ACTION_REQUEST_KEY = 'maverick.vault.actionRequest';

export type VaultMetricFilter = 'active-grants' | 'review-events' | null;

export type VaultViewState = {
  credentialPanel: CredentialPanel;
  metricFilter: VaultMetricFilter;
  query: string;
  selectedSecretId: string;
  tab: Tab;
};

export type VaultActionRequest = {
  action: 'new-credential' | 'rotate-credential';
  id: string;
};

export function readVaultViewState(): VaultViewState {
  if (typeof window === 'undefined') {
    return defaultVaultViewState();
  }
  try {
    const payload = JSON.parse(window.localStorage.getItem(VAULT_VIEW_STATE_KEY) || '{}') as Partial<VaultViewState>;
    return {
      credentialPanel: credentialPanelFromValue(payload.credentialPanel),
      metricFilter: metricFilterFromValue(payload.metricFilter),
      query: typeof payload.query === 'string' ? payload.query : '',
      selectedSecretId: typeof payload.selectedSecretId === 'string' ? payload.selectedSecretId : '',
      tab: tabFromValue(payload.tab) || 'credentials'
    };
  } catch {
    return defaultVaultViewState();
  }
}

export function writeVaultViewState(next: VaultViewState) {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(VAULT_VIEW_STATE_KEY, JSON.stringify(next));
}

export function notifyVaultViewStateChanged() {
  window.parent?.postMessage(
    {
      type: 'maverick.app.data-changed',
      owner_app_id: 'vault',
      resource: 'view-state'
    },
    window.location.origin
  );
}

export function notifyVaultDataChanged() {
  window.parent?.postMessage(
    {
      type: 'maverick.app.data-changed',
      owner_app_id: 'vault',
      resource: 'state'
    },
    window.location.origin
  );
}

export function writeVaultActionRequest(action: VaultActionRequest['action']) {
  if (typeof window === 'undefined') {
    return;
  }
  const request: VaultActionRequest = {
    action,
    id: typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : String(Date.now())
  };
  window.localStorage.setItem(VAULT_ACTION_REQUEST_KEY, JSON.stringify(request));
  window.parent?.postMessage(
    {
      type: 'maverick.app.data-changed',
      owner_app_id: 'vault',
      resource: 'action-request'
    },
    window.location.origin
  );
}

export function readVaultActionRequest(): VaultActionRequest | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    const payload = JSON.parse(window.localStorage.getItem(VAULT_ACTION_REQUEST_KEY) || '{}') as Partial<VaultActionRequest>;
    if ((payload.action === 'new-credential' || payload.action === 'rotate-credential') && typeof payload.id === 'string') {
      return { action: payload.action, id: payload.id };
    }
  } catch {
    return null;
  }
  return null;
}

function defaultVaultViewState(): VaultViewState {
  return { credentialPanel: '', metricFilter: null, query: '', selectedSecretId: '', tab: 'credentials' };
}

function credentialPanelFromValue(value: unknown): CredentialPanel {
  if (value === 'edit' || value === 'new') {
    return value;
  }
  return '';
}

function metricFilterFromValue(value: unknown): VaultMetricFilter {
  if (value === 'active-grants' || value === 'review-events') {
    return value;
  }
  return null;
}
