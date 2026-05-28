export type ReloadMode = 'view' | 'full';

export interface CalendarOAuthCallback {
  appId: string;
  code: string;
  state: string;
  error: string;
  redirectUri: string;
}

export function runtimeAppIdFromPathname(pathname: string) {
  const match = pathname.match(/\/api\/apps\/widgets\/([^/?#]+)/) || pathname.match(/\/apps\/([^/?#]+)/);
  if (!match?.[1]) {
    return 'calendar';
  }
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

export function mergeReloadMode(current: ReloadMode, requested: ReloadMode): ReloadMode {
  return current === 'full' || requested === 'full' ? 'full' : 'view';
}

export function eventIdFromParams(params: Record<string, unknown>) {
  const directEventId = scalarString(params.event_id);
  if (directEventId) {
    return directEventId;
  }
  const appPage = scalarString(params.app_page).replace(/^\/+|\/+$/g, '');
  const match = appPage.match(/^events\/([^/?#]+)$/);
  return match?.[1] ? decodeURIComponent(match[1]) : '';
}

export function calendarOAuthRedirectUri(appId: string, origin: string) {
  const normalizedOrigin = origin.replace(/\/+$/g, '');
  return `${normalizedOrigin}/apps/${encodeURIComponent(appId)}/oauth/callback`;
}

export function calendarOAuthCallbackFromLocation(pathname: string, search: string, origin: string): CalendarOAuthCallback | null {
  const match = pathname.match(/^\/apps\/([^/?#]+)\/oauth\/callback\/?$/);
  if (!match?.[1]) {
    return null;
  }
  const params = new URLSearchParams(search);
  const appId = safeDecodeURIComponent(match[1]);
  return {
    appId,
    code: scalarString(params.get('code')),
    state: scalarString(params.get('state')),
    error: scalarString(params.get('error')),
    redirectUri: `${origin.replace(/\/+$/g, '')}${pathname}`,
  };
}

export function scalarString(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function safeDecodeURIComponent(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
