// One request at a time, with a single trailing refresh for changes during a read.
export function createRefreshLoop({read, delay, onError, onBusy = () => {},
  visible = () => document.visibilityState !== "hidden", schedule = setTimeout, cancel = clearTimeout}) {
  let timer, flight, controller, queued = false, stopped = false, failures = 0;
  const pause = () => { cancel(timer); timer = undefined; };
  function refresh() {
    pause();
    if (stopped || !visible()) return Promise.resolve();
    if (flight) { queued = true; return flight; }
    controller = new AbortController();
    onBusy(true);
    flight = Promise.resolve().then(() => read(controller.signal)).then(() => {
      failures = 0;
    }).catch(error => {
      if (!stopped) { failures++; onError(error); }
    }).finally(() => {
      flight = null;
      onBusy(false);
      if (stopped || !visible()) { queued = false; return; }
      const wait = queued ? 0 : failures ? Math.min(60000, 5000 * 2 ** (failures - 1)) : delay();
      queued = false;
      timer = schedule(refresh, wait);
    });
    return flight;
  }
  return {refresh, pause, stop() { stopped = true; queued = false; pause(); controller?.abort(); }};
}

export const isPending = operation => ["queued", "running", "processing_media"].includes(operation.status);
export const isActiveConnection = connection => ["connecting", "connected"].includes(connection.status);
export function overviewDelay(overview) {
  if (overview.pending_count > 0 || overview.operations.some(isPending)) return 3000;
  return overview.connections.some(isActiveConnection) ? 10000 : 30000;
}
