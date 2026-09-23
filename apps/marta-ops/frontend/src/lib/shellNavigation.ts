import type { ViewId } from '../types';

export const DEFAULT_APP_ID = 'marta-ops';

const VIEW_IDS = new Set<ViewId>(['today', 'work', 'ideas']);

export function viewFromAppPage(value: unknown): ViewId | null {
  return typeof value === 'string' && VIEW_IDS.has(value as ViewId) ? value as ViewId : null;
}

export function mountedAppIdFromPath(
  pathname = typeof window === 'undefined' ? '' : window.location.pathname,
  fallback = DEFAULT_APP_ID,
): string {
  const match = /^\/api\/apps\/widgets\/([^/?#]+)/.exec(pathname) || /^\/apps\/([^/?#]+)/.exec(pathname);
  if (!match?.[1]) return fallback;
  try {
    return decodeURIComponent(match[1]) || fallback;
  } catch {
    return match[1] || fallback;
  }
}

export function postToShell(message: Record<string, unknown>) {
  window.parent?.postMessage(message, '*');
}

export function openApp(appId: string, params: Record<string, unknown>) {
  postToShell({ type: 'maverick.app.open-app', app_id: appId, params });
}

export function isMaverickParentMessage(event: MessageEvent) {
  return event.source === window.parent && event.origin === window.location.origin
    && Boolean(event.data) && typeof event.data === 'object';
}
