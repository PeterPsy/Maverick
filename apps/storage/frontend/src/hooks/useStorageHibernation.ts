import { useEffect, useRef, useState } from 'react';
import { registerMaverickAppHibernation, type MaverickResumeParams } from '@maverick/pwa-cache';

type Snapshot<T> = { view: T; scroll: number; files: number; folders: number };

export function useStorageHibernation<T>(options: {
  appId: string; ready: boolean; visible: boolean; fileCount: number; folderCount: number;
  hasMoreFiles: boolean; hasMoreFolders: boolean;
  capture: () => T | null;
  restore: (state: T, navigation: MaverickResumeParams) => Promise<void>;
  loadMoreFiles: () => Promise<void>; loadMoreFolders: () => Promise<void>;
}) {
  const current = useRef(options);
  current.current = options;
  const running = useRef(false);
  const visibility = useRef({ visible: options.visible, generation: 0, mounted: true });
  if (visibility.current.visible !== options.visible) {
    visibility.current.visible = options.visible;
    visibility.current.generation += 1;
  }
  const [attempt, setAttempt] = useState(0);
  const [pending, setPending] = useState<{
    state: Snapshot<T>; navigation: MaverickResumeParams;
    resolve: () => void; reject: (error: unknown) => void;
  } | null>(null);
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  useEffect(() => {
    visibility.current.mounted = true;
    return () => {
      visibility.current.mounted = false;
      visibility.current.generation += 1;
      pendingRef.current?.reject(new DOMException('Storage view disposed', 'AbortError'));
    };
  }, []);
  useEffect(() => registerMaverickAppHibernation({
    appId: options.appId,
    capture: () => {
      const value = current.current;
      if (!value.ready || running.current || pendingRef.current) return null;
      const view = value.capture();
      return view === null ? null : { params: {}, state: { view,
        scroll: document.querySelector<HTMLElement>('.storage-browser')?.scrollTop || 0,
        files: value.fileCount, folders: value.folderCount } satisfies Snapshot<T> };
    },
    restore: (snapshot, navigation) => new Promise<void>((resolve, reject) => {
      setPending({ state: snapshot.state as Snapshot<T>, navigation, resolve, reject });
    }),
  }), [options.appId]);

  useEffect(() => {
    if (!pending || !options.ready || !options.visible || running.current) return;
    running.current = true;
    const generation = visibility.current.generation;
    const interrupted = () => !visibility.current.mounted || generation !== visibility.current.generation;
    const nextPaint = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const restore = async () => {
      await current.current.restore(pending.state.view, pending.navigation);
      await nextPaint();
      if (interrupted()) return false;
      const explicit = Object.entries(pending.navigation).some(([key, value]) => key !== 'workspace_id' && value !== null && value !== '');
      if (!explicit) {
        for (const kind of ['files', 'folders'] as const) {
          while (true) {
            const value = current.current;
            const count = kind === 'files' ? value.fileCount : value.folderCount;
            const more = kind === 'files' ? value.hasMoreFiles : value.hasMoreFolders;
            if (count >= pending.state[kind] || !more) break;
            await (kind === 'files' ? value.loadMoreFiles() : value.loadMoreFolders());
            await nextPaint();
            if (interrupted()) return false;
            if ((kind === 'files' ? current.current.fileCount : current.current.folderCount) <= count) break;
          }
        }
        const viewport = document.querySelector<HTMLElement>('.storage-browser');
        if (viewport) viewport.scrollTop = Math.max(0, pending.state.scroll || 0);
      }
      return true;
    };
    const retry = () => { if (visibility.current.mounted) setAttempt((value) => value + 1); };
    void restore().then((complete) => {
      running.current = false;
      if (!complete) { retry(); return; }
      pending.resolve();
      setPending(null);
    }, (error) => {
      running.current = false;
      if (interrupted()) { retry(); return; }
      pending.reject(error);
      setPending(null);
    });
  }, [pending, options.ready, options.visible, attempt]);
}
