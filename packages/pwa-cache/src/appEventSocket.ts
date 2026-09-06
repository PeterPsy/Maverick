/** Live app events have no replay cursor: reopening must refresh display reads. */
export function connectAppEventSocket<T>(
  onEvent: (event: T) => void,
  onReconnect: () => void,
): () => void {
  if (typeof WebSocket === "undefined" || typeof window === "undefined") return () => {};
  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;
  let interrupted = false;
  let failures = 0;

  function scheduleReconnect(): void {
    if (disposed || timer !== undefined) return;
    interrupted = true;
    const delay = Math.min(30_000, 1_000 * 2 ** Math.min(failures++, 5));
    timer = setTimeout(() => { timer = undefined; connect(); }, delay);
  }

  function connect(): void {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    let current: WebSocket;
    try {
      current = new WebSocket(`${protocol}//${window.location.host}/api/apps/events/ws`);
    } catch {
      scheduleReconnect();
      return;
    }
    socket = current;
    let opened = false;
    const active = () => !disposed && socket === current;
    current.onopen = () => {
      if (!active() || opened) return;
      opened = true;
      failures = 0;
      if (!interrupted) return;
      interrupted = false;
      onReconnect();
    };
    current.onmessage = (message) => {
      if (!active()) return;
      let event: T;
      try { event = JSON.parse(message.data) as T; } catch { return; }
      onEvent(event);
    };
    current.onclose = () => {
      if (!active()) return;
      socket = null;
      scheduleReconnect();
    };
    current.onerror = () => { if (active()) current.close(); };
  }

  connect();
  return () => {
    disposed = true;
    clearTimeout(timer);
    socket?.close();
    socket = null;
  };
}
