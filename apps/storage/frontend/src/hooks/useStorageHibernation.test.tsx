// @vitest-environment happy-dom
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import type { registerMaverickAppHibernation } from '@maverick/pwa-cache';
import { useStorageHibernation } from './useStorageHibernation';

const lifecycle = vi.hoisted(() => ({ options: null as Parameters<typeof registerMaverickAppHibernation>[0] | null }));
vi.mock('@maverick/pwa-cache', () => ({ registerMaverickAppHibernation: (options: typeof lifecycle.options) => {
  lifecycle.options = options;
  return () => { lifecycle.options = null; };
} }));

it('restores the folder, loaded pages and scroll before acknowledging, and pins editing state', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  const restored = vi.fn();
  const load = vi.fn();
  let editing = false;
  let folder = '';
  function Harness() {
    const [files, setFiles] = useState(0);
    useStorageHibernation({ appId: 'storage', ready: true, visible: true, fileCount: files, folderCount: 0,
      hasMoreFiles: files > 0 && files < 300, hasMoreFolders: false,
      capture: () => editing ? null : { folder },
      restore: async (state) => { folder = state.folder; await Promise.resolve(); setFiles(100); },
      loadMoreFiles: async () => { load(); setFiles((count) => count + 100); }, loadMoreFolders: async () => {},
    });
    return <div className="storage-browser" />;
  }
  try {
    await act(async () => root.render(<Harness />));
    await act(async () => {
      void Promise.resolve(lifecycle.options!.restore({ params: {}, state: {
        view: { folder: 'generated/reports' }, scroll: 500, files: 300, folders: 0,
      } }, {})).then(restored);
    });
    for (let count = 0; count < 5; count += 1) {
      await act(async () => { await new Promise((resolve) => requestAnimationFrame(resolve)); });
    }
    expect(folder).toBe('generated/reports');
    expect(load).toHaveBeenCalledTimes(2);
    expect(restored).toHaveBeenCalledOnce();
    expect(container.querySelector<HTMLElement>('.storage-browser')!.scrollTop).toBe(500);
    editing = true;
    expect(lifecycle.options!.capture()).toBeNull();
  } finally { await act(async () => root.unmount()); container.remove(); }
});

it('keeps the snapshot pending when hidden during restore and resumes it on visibility', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  let release!: () => void;
  const interruptedRead = new Promise<void>((resolve) => { release = resolve; });
  const restore = vi.fn().mockImplementationOnce(() => interruptedRead).mockResolvedValue(undefined);
  const acknowledged = vi.fn();
  function Harness({ visible }: { visible: boolean }) {
    useStorageHibernation({ appId: 'storage', ready: true, visible, fileCount: 100, folderCount: 0,
      hasMoreFiles: false, hasMoreFolders: false, capture: () => ({ folder: 'reports' }),
      restore, loadMoreFiles: async () => {}, loadMoreFolders: async () => {},
    });
    return <div className="storage-browser" />;
  }
  try {
    await act(async () => root.render(<Harness visible />));
    await act(async () => {
      void Promise.resolve(lifecycle.options!.restore({ params: {}, state: {
        view: { folder: 'reports' }, scroll: 250, files: 100, folders: 0,
      } }, {})).then(acknowledged);
    });
    await act(async () => root.render(<Harness visible={false} />));
    await act(async () => { release(); await interruptedRead; });
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(resolve)); });
    expect(acknowledged).not.toHaveBeenCalled();
    expect(lifecycle.options!.capture()).toBeNull();
    await act(async () => root.render(<Harness visible />));
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(resolve)); });
    expect(restore).toHaveBeenCalledTimes(2);
    expect(acknowledged).toHaveBeenCalledOnce();
    expect(container.querySelector<HTMLElement>('.storage-browser')!.scrollTop).toBe(250);
  } finally { await act(async () => root.unmount()); container.remove(); }
});
