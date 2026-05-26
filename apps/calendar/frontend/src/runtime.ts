export type ReloadMode = 'view' | 'full';

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

export function scalarString(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}
