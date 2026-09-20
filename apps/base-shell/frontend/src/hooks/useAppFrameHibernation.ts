import { useEffect, useRef, type Dispatch, type RefObject, type SetStateAction } from 'react';
import { appSnapshotBytes, MAX_APP_SNAPSHOT_BYTES, type MaverickAppSnapshot, type MaverickResumeParams } from '@maverick/pwa-cache';
import type { AppRegistryItem } from '../api';
import { isMaverickFrameMessage, postToMaverickFrame } from '../iframePolicy';

type MountedApp = { app: AppRegistryItem; mountKey: string };
type SavedApp = { snapshot: MaverickAppSnapshot; requestId: string; bytes: number; source?: Window | null };
const MAX_SAVED_BYTES = 2 * 1024 * 1024;

/** Keep active + previous views warm; only certified, consenting apps can be removed. */
export function useAppFrameHibernation(options: {
  activeKey: string; scope: string; ready: boolean; mounted: MountedApp[];
  frames: RefObject<Record<string, HTMLIFrameElement | null>>;
  setMounted: Dispatch<SetStateAction<MountedApp[]>>;
}) {
  const state = useRef({ scope: options.scope, recent: [] as string[], serial: 0,
    saved: new Map<string, SavedApp>(), pending: new Map<string, { id: string; expires: number; source: Window | null }>() });
  const latest = useRef(options);
  latest.current = options;
  if (state.current.scope !== options.scope) {
    state.current = { scope: options.scope, recent: [], serial: 0, saved: new Map(), pending: new Map() };
  }
  const current = state.current;
  if (current.recent[0] !== options.activeKey) {
    current.recent = [options.activeKey, ...current.recent.filter((key) => key !== options.activeKey)].slice(0, 2);
    current.pending.clear();
  }

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const { mounted, frames, setMounted } = latest.current;
      const item = mounted.find(({ app }) => app.app_id === event.data?.app_id);
      if (!item || !item.app.frontend_resumable || !isMaverickFrameMessage(event, frames.current[item.app.app_id])) return;
      const current = state.current;
      if (event.data.type === 'maverick.app.resumed') {
        const saved = current.saved.get(item.mountKey);
        if (saved && saved.requestId === event.data.request_id && saved.source === event.source) current.saved.delete(item.mountKey);
        return;
      }
      const pending = current.pending.get(item.mountKey);
      if (event.data.type !== 'maverick.app.hibernated' || !pending || pending.id !== event.data.request_id
          || pending.source !== event.source || pending.expires < Date.now() || current.recent.includes(item.mountKey)) return;
      current.pending.delete(item.mountKey);
      const snapshot = event.data.snapshot as MaverickAppSnapshot | null;
      if (!snapshot || !snapshot.params || typeof snapshot.params !== 'object' || Array.isArray(snapshot.params)
          || Object.values(snapshot.params).some((value) => value !== null && !['string', 'boolean'].includes(typeof value))) return;
      const bytes = appSnapshotBytes(snapshot);
      const total = [...current.saved.entries()].reduce((sum, [key, value]) => sum + (key === item.mountKey ? 0 : value.bytes), bytes);
      if (bytes > MAX_APP_SNAPSHOT_BYTES || total > MAX_SAVED_BYTES) return;
      current.saved.set(item.mountKey, { snapshot, requestId: pending.id, bytes });
      setMounted((items) => items.filter(({ mountKey }) => mountKey !== item.mountKey));
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  useEffect(() => {
    if (!options.ready) return;
    const current = state.current;
    for (const { app, mountKey } of options.mounted) {
      if (!app.frontend_resumable || current.recent.includes(mountKey) || current.pending.has(mountKey) || current.saved.has(mountKey)) continue;
      const frame = options.frames.current[app.app_id];
      if (!frame?.contentWindow) continue;
      const id = `${options.scope}:${++current.serial}`;
      current.pending.set(mountKey, { id, expires: Date.now() + 1000, source: frame.contentWindow });
      postToMaverickFrame(frame, { type: 'maverick.app.hibernate', app_id: app.app_id, request_id: id });
    }
  }, [options.activeKey, options.ready, options.mounted]);

  return (appId: string, navigation: MaverickResumeParams): boolean => {
    const { mounted, frames } = latest.current;
    const item = mounted.find(({ app }) => app.app_id === appId);
    const saved = item && state.current.saved.get(item.mountKey);
    const frame = frames.current[appId];
    if (!saved || !frame?.contentWindow) return false;
    saved.source = frame.contentWindow;
    postToMaverickFrame(frame, { type: 'maverick.app.resume', app_id: appId,
      request_id: saved.requestId, snapshot: saved.snapshot, navigation });
    return true;
  };
}
