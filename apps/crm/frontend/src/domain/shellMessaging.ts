/** Core-injected origin: never infer trust from a widget URL, referrer or message. */
export function postToShell(message: Record<string, unknown>): boolean {
  const origin = (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: unknown }).__MAVERICK_PLATFORM_ORIGIN__;
  if (window.parent === window || typeof origin !== 'string') return false;
  try {
    const url = new URL(origin);
    if (url.origin !== origin || !['http:', 'https:'].includes(url.protocol)) return false;
    window.parent.postMessage(message, origin);
    return true;
  } catch {
    return false;
  }
}
