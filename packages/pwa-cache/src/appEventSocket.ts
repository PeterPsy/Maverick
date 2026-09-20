import { readMaverickAppFrameContext } from './appFrameContext';
import { isExactMaverickParentMessage } from './dataCacheBrokerProtocol';
import { maverickAppIsVisible, observeMaverickVisibility } from './appVisibility';

type Subscriber = { event: (event: unknown) => void; refresh: () => void };
const subscribers = new Set<Subscriber>();
let stopTransport: (() => void) | null = null;

/** One transport per document; isolated app frames receive their shell's stream. */
export function connectAppEventSocket<T>(onEvent: (event: T) => void, onReconnect: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const subscriber: Subscriber = { event: onEvent as (event: unknown) => void, refresh: onReconnect };
  subscribers.add(subscriber);
  if (!stopTransport) stopTransport = startTransport();
  return () => {
    subscribers.delete(subscriber);
    if (!subscribers.size) { stopTransport?.(); stopTransport = null; }
  };
}

function startTransport(): () => void {
  const context = readMaverickAppFrameContext();
  const embedded = Boolean(context && window.parent && window.parent !== window);
  const documentSuspended = () => Boolean(globalThis.document?.hidden || globalThis.navigator?.onLine === false);
  let awaitingParentResume = embedded && documentSuspended();
  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;
  let interrupted = false;
  let failures = 0;
  const visible = maverickAppIsVisible;
  let wasVisible = visible();
  interrupted = !wasVisible;
  const refresh = () => { for (const subscriber of subscribers) subscriber.refresh(); };
  const deliver = (event: unknown) => { for (const subscriber of subscribers) subscriber.event(event); };

  function scheduleReconnect(): void {
    interrupted = true;
    if (disposed || !visible() || timer !== undefined) return;
    const delay = Math.min(30_000, 1_000 * 2 ** Math.min(failures++, 5) * (0.8 + Math.random() * 0.4));
    timer = setTimeout(() => { timer = undefined; connect(); }, delay);
  }

  function connect(): void {
    if (disposed || embedded || !visible() || socket || typeof WebSocket === 'undefined') return;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    let current: WebSocket;
    try { current = new WebSocket(`${protocol}//${window.location.host}/api/apps/events/ws`); }
    catch { scheduleReconnect(); return; }
    socket = current;
    let opened = false;
    const active = () => !disposed && socket === current;
    current.onopen = () => {
      if (!active() || opened) return;
      opened = true;
      failures = 0;
      if (interrupted) { interrupted = false; refresh(); }
    };
    current.onmessage = (message) => {
      if (!active() || !visible()) return;
      let event: unknown;
      try { event = JSON.parse(message.data); } catch { return; }
      deliver(event);
    };
    current.onclose = () => { if (active()) { socket = null; scheduleReconnect(); } };
    current.onerror = () => { if (active()) current.close(); };
  }

  function updateVisibility(): void {
    const next = visible();
    if (next === wasVisible) return;
    wasVisible = next;
    if (!next) {
      if (embedded && documentSuspended()) awaitingParentResume = true;
      interrupted = true;
      clearTimeout(timer); timer = undefined;
      const previous = socket; socket = null; previous?.close();
    } else if (embedded) {
      if (interrupted && !awaitingParentResume) { interrupted = false; refresh(); }
    } else connect();
  }

  // A frame can already be hidden when the entire document goes offline or into
  // the background. Wait for the shell's live stream before refreshing it.
  function onDocumentSuspended(): void {
    if (embedded && documentSuspended()) awaitingParentResume = true;
  }

  function onMessage(message: MessageEvent): void {
    if (!embedded || !isExactMaverickParentMessage(message) || !message.data || typeof message.data !== 'object') return;
    const payload = message.data;
    if (payload.type === 'maverick.app.events-resync') {
      awaitingParentResume = false;
      if (visible()) { interrupted = false; refresh(); } else interrupted = true;
    } else if (payload.type === 'maverick.app.event' && payload.event && typeof payload.event === 'object') {
      if (payload.event.workspace_id && payload.event.workspace_id !== context!.workspaceId) return;
      if (visible()) deliver(payload.event); else interrupted = true;
    }
  }

  const stopVisibility = observeMaverickVisibility(updateVisibility);
  window.addEventListener?.('offline', onDocumentSuspended);
  globalThis.document?.addEventListener('visibilitychange', onDocumentSuspended);
  window.addEventListener?.('message', onMessage);
  connect();
  return () => {
    disposed = true;
    clearTimeout(timer);
    const previous = socket; socket = null; previous?.close();
    stopVisibility();
    window.removeEventListener?.('offline', onDocumentSuspended);
    globalThis.document?.removeEventListener('visibilitychange', onDocumentSuspended);
    window.removeEventListener?.('message', onMessage);
  };
}
