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
    stage: 'view' | 'files' | 'folders' | 'scroll'; previousCount?: number;
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
      setPending({ state: snapshot.state as Snapshot<T>, navigation, resolve, reject, stage: 'view' });
    }),
  }), [options.appId]);

  useEffect(() => {
    if (!pending || !options.ready || !options.visible || running.current) return;
    running.current = true;
    const generation = visibility.current.generation;
    const interrupted = () => !visibility.current.mounted || generation !== visibility.current.generation;
    let next: { stage: typeof pending.stage; previousCount?: number } | null = null;
    const advance = (stage: typeof pending.stage, previousCount?: number) => {
      next = { stage, previousCount };
    };
    const restore = async () => {
      const explicit = Object.entries(pending.navigation).some(([key, value]) => key !== 'workspace_id' && value !== null && value !== '');
      if (pending.stage === 'view') {
        await current.current.restore(pending.state.view, pending.navigation);
        if (interrupted()) return false;
        advance(explicit ? 'scroll' : 'files');
        return true;
      }
      if (pending.stage === 'files' || pending.stage === 'folders') {
        const kind = pending.stage;
        const value = current.current;
        const count = kind === 'files' ? value.fileCount : value.folderCount;
        const more = kind === 'files' ? value.hasMoreFiles : value.hasMoreFolders;
        if (count >= pending.state[kind] || !more || count === pending.previousCount) {
          advance(kind === 'files' ? 'folders' : 'scroll');
        } else {
          await (kind === 'files' ? value.loadMoreFiles() : value.loadMoreFolders());
          if (interrupted()) return false;
          advance(kind, count);
        }
        return true;
      }
      if (!explicit) {
        const viewport = document.querySelector<HTMLElement>('.storage-browser');
        if (viewport) viewport.scrollTop = Math.max(0, pending.state.scroll || 0);
      }
      pending.resolve();
      setPending(null);
      return true;
    };
    const retry = () => { if (visibility.current.mounted) setAttempt((value) => value + 1); };
    void restore().then((complete) => {
      running.current = false;
      if (!visibility.current.mounted) return;
      if (!complete) {
        setPending(value => value === pending ? { ...value, stage: 'view', previousCount: undefined } : value);
        retry();
      } else if (next) {
        // A stage transition commits the preceding page before reading its count.
        // A single RAF is not a React commit barrier and can observe stale props.
        const progress = next;
        setPending(value => value === pending ? { ...value, ...progress } : value);
      }
    }, (error) => {
      running.current = false;
      if (!visibility.current.mounted) return;
      if (interrupted()) {
        setPending(value => value === pending ? { ...value, stage: 'view', previousCount: undefined } : value);
        retry(); return;
      }
      pending.reject(error);
      setPending(null);
    });
  }, [pending, options.ready, options.visible, attempt]);
}
