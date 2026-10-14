import { isExactLoopinoParentMessage } from './dataCacheBrokerProtocol';
import { loopinoAppIsVisible, observeLoopinoVisibility } from './appVisibility';

export type LoopinoResumeParams = Record<string, string | boolean | null>;
export type LoopinoAppSnapshot = { params: LoopinoResumeParams; state: unknown };
export const MAX_APP_SNAPSHOT_BYTES = 64 * 1024;
let blockers = 0;

/** Components owning non-serializable work keep their app alive until cleanup. */
export function preventLoopinoAppHibernation(): () => void {
  blockers += 1;
  let released = false;
  return () => { if (!released) { released = true; blockers -= 1; } };
}

export function appSnapshotBytes(snapshot: unknown): number {
  try { return JSON.stringify(snapshot).length * 2; } catch { return Infinity; }
}

/** Opt-in app lifecycle. A busy app returns null and remains mounted. */
export function registerLoopinoAppHibernation(options: {
  appId: string;
  capture: () => LoopinoAppSnapshot | null;
  restore: (snapshot: LoopinoAppSnapshot, navigation: LoopinoResumeParams) => void | Promise<void>;
}): () => void {
  const stopVisibility = observeLoopinoVisibility(() => {});
  const restored = new Set<string>();
  let disposed = false;
  const listener = (event: MessageEvent) => {
    if (!isExactLoopinoParentMessage(event) || event.data?.app_id !== options.appId
        || typeof event.data.request_id !== 'string') return;
    const { type, request_id: requestId } = event.data;
    const reply = (payload: Record<string, unknown>) => {
      if (!disposed) window.parent.postMessage({ app_id: options.appId, request_id: requestId, ...payload }, event.origin);
    };
    if (type === 'loopino.app.hibernate') {
      let snapshot: LoopinoAppSnapshot | null = null;
      try {
        const media = globalThis.document?.querySelectorAll?.<HTMLMediaElement>('audio, video') ?? [];
        const ownsMedia = [...media].some((element) => !element.paused || element.currentTime > 0);
        if (!blockers && !ownsMedia && !loopinoAppIsVisible()) snapshot = options.capture();
      } catch { /* Keep the app mounted. */ }
      if (snapshot && appSnapshotBytes(snapshot) > MAX_APP_SNAPSHOT_BYTES) snapshot = null;
      reply({ type: 'loopino.app.hibernated', snapshot });
    } else if (type === 'loopino.app.resume' && !restored.has(requestId)) {
      const snapshot = event.data.snapshot as LoopinoAppSnapshot;
      if (!snapshot || appSnapshotBytes(snapshot) > MAX_APP_SNAPSHOT_BYTES) return;
      restored.add(requestId);
      Promise.resolve().then(() => options.restore(snapshot, event.data.navigation || {})).then(() => {
        reply({ type: 'loopino.app.resumed' });
      }).catch(() => { restored.delete(requestId); });
    }
  };
  window.addEventListener('message', listener);
  return () => { disposed = true; stopVisibility(); window.removeEventListener('message', listener); };
}
