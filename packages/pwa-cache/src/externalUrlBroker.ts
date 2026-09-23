export type ExternalUrlDisposition = 'new-window' | 'same-window';

type ExternalUrlParent = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type ExternalUrlRequestOptions = {
  currentWindow?: unknown;
  disposition?: ExternalUrlDisposition;
  origin?: string;
  ownerAppId?: string;
  parentWindow?: ExternalUrlParent | null;
  widgetId?: string;
};

export function isStandaloneWebApp(
  displayModeStandalone = typeof window !== 'undefined'
    && window.matchMedia?.('(display-mode: standalone)').matches === true,
  navigatorStandalone = typeof navigator !== 'undefined'
    && (navigator as Navigator & { standalone?: boolean }).standalone === true,
): boolean {
  return displayModeStandalone || navigatorStandalone;
}

export function requestParentExternalUrl(value: unknown, options: ExternalUrlRequestOptions = {}): boolean {
  const url = absoluteHttpUrl(value);
  if (!url) return false;
  const currentWindow = options.currentWindow ?? (typeof window === 'undefined' ? null : window);
  const parentWindow = options.parentWindow ?? (typeof window === 'undefined' ? null : window.parent);
  if (!parentWindow || parentWindow === currentWindow) return false;
  const message: Record<string, string> = {
    type: 'maverick.app.external-url',
    disposition: options.disposition || 'new-window',
    url,
  };
  if (options.ownerAppId) message.owner_app_id = options.ownerAppId;
  if (options.widgetId) message.widget_id = options.widgetId;
  parentWindow.postMessage(message, options.origin || platformOrigin(currentWindow) || '*');
  return true;
}

function absoluteHttpUrl(value: unknown): string | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
  } catch {
    return null;
  }
}

function platformOrigin(currentWindow: unknown): string | null {
  const value = (currentWindow as { __MAVERICK_PLATFORM_ORIGIN__?: unknown } | null)
    ?.__MAVERICK_PLATFORM_ORIGIN__;
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return url.origin === value && (url.protocol === 'http:' || url.protocol === 'https:') ? value : null;
  } catch {
    return null;
  }
}
