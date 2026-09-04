export type StorageOAuthCallback = {
  appId: string;
  code: string;
  error: string;
  redirectUri: string;
  state: string;
};

export type StorageOAuthNavigationDisposition = 'new-window' | 'same-window';

export function storageOAuthRedirectUri(appId: string, origin: string) {
  const normalizedOrigin = origin.replace(/\/+$/g, '');
  return `${normalizedOrigin}/apps/${encodeURIComponent(appId)}/oauth/callback`;
}

export function maverickPlatformOrigin(): string {
  const value = (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: unknown }).__MAVERICK_PLATFORM_ORIGIN__;
  return typeof value === 'string' && /^https?:\/\//u.test(value) ? value : window.location.origin;
}

export function storageOAuthNavigationDisposition(
  displayModeStandalone = window.matchMedia?.('(display-mode: standalone)').matches === true,
  navigatorStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true,
): StorageOAuthNavigationDisposition {
  return displayModeStandalone || navigatorStandalone ? 'same-window' : 'new-window';
}

export function storageOAuthCallbackFromLocation(pathname: string, search: string, origin: string): StorageOAuthCallback | null {
  const match = pathname.match(/^\/apps\/([^/?#]+)\/oauth\/callback\/?$/);
  if (!match?.[1]) {
    return null;
  }
  const params = new URLSearchParams(search);
  return {
    appId: safeDecodeURIComponent(match[1]),
    code: scalarString(params.get('code')),
    error: scalarString(params.get('error')),
    redirectUri: `${origin.replace(/\/+$/g, '')}${pathname}`,
    state: scalarString(params.get('state')),
  };
}

function scalarString(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function safeDecodeURIComponent(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
