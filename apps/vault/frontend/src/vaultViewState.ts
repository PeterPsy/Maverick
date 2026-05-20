import { Tab } from './vaultTypes';
import { tabFromValue } from './vaultUtils';

export const VAULT_VIEW_STATE_KEY = 'maverick.vault.viewState';
export const VAULT_ACTION_REQUEST_KEY = 'maverick.vault.actionRequest';

export type VaultMetricFilter = 'all-secrets' | 'active-secrets' | 'active-grants' | 'review-events' | null;

export type VaultViewState = {
  metricFilter: VaultMetricFilter;
  query: string;
  tab: Tab;
};

export type VaultActionRequest = {
  action: 'submit-secret' | 'submit-grant';
  id: string;
};

export function readVaultViewState(): VaultViewState {
  if (typeof window === 'undefined') {
    return defaultVaultViewState();
  }
  try {
    const payload = JSON.parse(window.localStorage.getItem(VAULT_VIEW_STATE_KEY) || '{}') as Partial<VaultViewState>;
    return {
      metricFilter: metricFilterFromValue(payload.metricFilter),
      query: typeof payload.query === 'string' ? payload.query : '',
      tab: tabFromValue(payload.tab) || 'secrets'
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
    if ((payload.action === 'submit-secret' || payload.action === 'submit-grant') && typeof payload.id === 'string') {
      return { action: payload.action, id: payload.id };
    }
  } catch {
    return null;
  }
  return null;
}

function defaultVaultViewState(): VaultViewState {
  return { metricFilter: null, query: '', tab: 'secrets' };
}

function metricFilterFromValue(value: unknown): VaultMetricFilter {
  if (value === 'all-secrets' || value === 'active-secrets' || value === 'active-grants' || value === 'review-events') {
    return value;
  }
  return null;
}
