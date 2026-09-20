import { isExactMaverickParentMessage } from './dataCacheBrokerProtocol';
import { maverickAppIsVisible, observeMaverickVisibility } from './appVisibility';

export type MaverickResumeParams = Record<string, string | boolean | null>;
export type MaverickAppSnapshot = { params: MaverickResumeParams; state: unknown };
export const MAX_APP_SNAPSHOT_BYTES = 64 * 1024;
let blockers = 0;

/** Components owning non-serializable work keep their app alive until cleanup. */
export function preventMaverickAppHibernation(): () => void {
  blockers += 1;
  let released = false;
  return () => { if (!released) { released = true; blockers -= 1; } };
}

export function appSnapshotBytes(snapshot: unknown): number {
  try { return JSON.stringify(snapshot).length * 2; } catch { return Infinity; }
}

/** Opt-in app lifecycle. A busy app returns null and remains mounted. */
export function registerMaverickAppHibernation(options: {
  appId: string;
  capture: () => MaverickAppSnapshot | null;
  restore: (snapshot: MaverickAppSnapshot, navigation: MaverickResumeParams) => void | Promise<void>;
}): () => void {
  const stopVisibility = observeMaverickVisibility(() => {});
  const restored = new Set<string>();
  let disposed = false;
  const listener = (event: MessageEvent) => {
    if (!isExactMaverickParentMessage(event) || event.data?.app_id !== options.appId
        || typeof event.data.request_id !== 'string') return;
    const { type, request_id: requestId } = event.data;
    const reply = (payload: Record<string, unknown>) => {
      if (!disposed) window.parent.postMessage({ app_id: options.appId, request_id: requestId, ...payload }, event.origin);
    };
    if (type === 'maverick.app.hibernate') {
      let snapshot: MaverickAppSnapshot | null = null;
      try { if (!blockers && !maverickAppIsVisible()) snapshot = options.capture(); } catch { /* Keep the app mounted. */ }
      if (snapshot && appSnapshotBytes(snapshot) > MAX_APP_SNAPSHOT_BYTES) snapshot = null;
      reply({ type: 'maverick.app.hibernated', snapshot });
    } else if (type === 'maverick.app.resume' && !restored.has(requestId)) {
      const snapshot = event.data.snapshot as MaverickAppSnapshot;
      if (!snapshot || appSnapshotBytes(snapshot) > MAX_APP_SNAPSHOT_BYTES) return;
      restored.add(requestId);
      Promise.resolve().then(() => options.restore(snapshot, event.data.navigation || {})).then(() => {
        reply({ type: 'maverick.app.resumed' });
      }).catch(() => { restored.delete(requestId); });
    }
  };
  window.addEventListener('message', listener);
  return () => { disposed = true; stopVisibility(); window.removeEventListener('message', listener); };
}
