// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { callBackend, cachedWorkspaceSnapshot, type PreviewPayload, type WorkspaceSnapshot } from './api';
import { deferred, preview, snapshot } from './App.recovery.fixtures';

vi.mock('./api', () => ({
  callBackend: vi.fn(), cachedWorkspaceSnapshot: vi.fn(), invalidateWorkspaceSnapshots: vi.fn()
}));

describe('Website Studio snapshot recovery', () => {
  let host: HTMLDivElement;
  let root: Root;
  let current: WorkspaceSnapshot;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    host = document.createElement('div');
    root = createRoot(host);
    current = snapshot('a');
    vi.mocked(cachedWorkspaceSnapshot).mockImplementation(() => ({ fresh: Promise.resolve(current), revalidated: Promise.resolve(null) }));
    vi.mocked(callBackend).mockImplementation(async (body) => {
      if (body.action !== 'build_preview') throw new Error(`Unexpected action: ${body.action}`);
      return preview(current.versions.source_version, String(body.route));
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    vi.resetAllMocks();
  });

  function frame() { return host.querySelector<HTMLIFrameElement>('.site-canvas iframe'); }
  function expectPreview(version: string, route = '/') {
    expect(frame()?.dataset.previewUrl).toContain(preview(version, route).preview_url);
  }
  async function message(data: Record<string, unknown>, origin = window.location.origin, source: Window | null = window) {
    await act(async () => { window.dispatchEvent(new MessageEvent('message', { data, origin, source })); });
  }
  function changed(resource = 'records') {
    // This is the ordinary owner message sent by Shell after socket recovery.
    return message({ type: 'maverick.app.data-changed', owner_app_id: 'website-studio', resource });
  }
  function navigate(route: string) {
    return message({ type: 'maverick.app.navigate', params: { site_id: 'site', route } });
  }

  it.each(['records', 'source', 'working-state', 'navigation', 'preview', 'activity', 'settings', 'view-selection'])(
    'reconciles the preview with the new snapshot after %s, regardless of alias order', async (resource) => {
      await act(async () => { root.render(<App />); });
      expectPreview('a');
      current = snapshot('b');
      await changed(resource);
      expect(cachedWorkspaceSnapshot).toHaveBeenCalledTimes(2);
      expectPreview('b');
      expect(callBackend).not.toHaveBeenCalled();
    }
  );

  it('keeps the preview frame mounted during recovery and invalidates other warmed routes', async () => {
    await act(async () => { root.render(<App />); });
    const originalFrame = frame();
    await navigate('/about');
    expectPreview('a', '/about');
    await navigate('/');
    expectPreview('a');
    expect(callBackend).toHaveBeenCalledTimes(1);

    current = snapshot('b');
    await changed();
    expectPreview('b');
    expect(frame()).toBe(originalFrame);
    await navigate('/about');
    expectPreview('b', '/about');
    expect(callBackend).toHaveBeenCalledTimes(2);
    expect(frame()).toBe(originalFrame);
  });

  it('preserves warmed route reuse when a reread has the same snapshot revision', async () => {
    await act(async () => { root.render(<App />); });
    await navigate('/about');
    await navigate('/');
    current = snapshot('a'); // New object, unchanged content revision.
    await changed();
    await navigate('/about');
    expectPreview('a', '/about');
    expect(callBackend).toHaveBeenCalledTimes(1);
  });

  it('prefers the snapshot-supplied preview over RAM within the same cache generation', async () => {
    await act(async () => { root.render(<App />); });
    current = snapshot('a');
    current.project!.latest_preview = snapshot('b').project!.latest_preview;
    await changed();
    expectPreview('b');
    expect(callBackend).not.toHaveBeenCalled();
  });

  it('updates derived previews when a stale initial snapshot revalidates without another event', async () => {
    const revalidation = deferred<WorkspaceSnapshot | null>();
    vi.mocked(cachedWorkspaceSnapshot).mockReturnValueOnce({ fresh: Promise.resolve(current), revalidated: revalidation.promise });
    await act(async () => { root.render(<App />); });
    expectPreview('a');
    await act(async () => {
      current = snapshot('b');
      revalidation.resolve(current);
    });
    expectPreview('b');
    expect(callBackend).not.toHaveBeenCalled();
  });

  it('never reuses a pre-recovery preview build or lets its completion erase the replacement request', async () => {
    const oldBuild = deferred<PreviewPayload>();
    const newBuild = deferred<PreviewPayload>();
    vi.mocked(callBackend).mockReturnValueOnce(oldBuild.promise).mockReturnValueOnce(newBuild.promise);
    await act(async () => { root.render(<App />); });
    await navigate('/about');
    expect(callBackend).toHaveBeenCalledTimes(1);

    current = snapshot('b');
    await changed();
    await navigate('/about');
    expect(callBackend).toHaveBeenCalledTimes(2);
    await act(async () => { oldBuild.resolve(preview('a', '/about')); });
    expectPreview('b');
    await navigate('/about');
    expect(callBackend).toHaveBeenCalledTimes(2);
    await act(async () => { newBuild.resolve(preview('b', '/about')); });
    expectPreview('b', '/about');
  });

  it('builds a current preview when the recovered snapshot no longer has a compatible one', async () => {
    await act(async () => { root.render(<App />); });
    current = snapshot('b', false);
    await changed();
    expectPreview('b');
    expect(callBackend).toHaveBeenCalledTimes(1);
  });

  it('refreshes visible site details along with a recovered preview', async () => {
    vi.mocked(callBackend).mockImplementation(async (body) => {
      if (body.action === 'site_status') return { site: current.project!.site, changed_files_count: current.versions.source_version === 'a' ? 0 : 1 };
      if (body.action === 'list_changes') return { site_id: 'site', working_diff: [], builds: [], deployments: [], publish_requests: [], approval_events: [] };
      throw new Error(`Unexpected action: ${body.action}`);
    });
    await act(async () => { root.render(<App />); });
    await message({ type: 'maverick.app.navigate', params: { site_id: 'site', info_panel: '1' } });
    const changedFiles = () => Array.from(host.querySelectorAll('.website-info-metric'))
      .find((metric) => metric.querySelector('span')?.textContent === 'changed')?.querySelector('strong')?.textContent;
    expect(changedFiles()).toBe('0');
    current = snapshot('b');
    await changed();
    expectPreview('b');
    expect(changedFiles()).toBe('1');
  });

  it('ignores late snapshots from an obsolete refresh, including their cache invalidation', async () => {
    await act(async () => { root.render(<App />); });
    const oldRead = deferred<WorkspaceSnapshot>();
    vi.mocked(cachedWorkspaceSnapshot).mockReturnValueOnce({ fresh: oldRead.promise, revalidated: Promise.resolve(null) });
    await changed();
    current = snapshot('b');
    await changed();
    await navigate('/about');
    await act(async () => { oldRead.resolve(snapshot('a')); });
    expectPreview('b', '/about');
    await navigate('/');
    await navigate('/about');
    expectPreview('b', '/about');
    expect(callBackend).toHaveBeenCalledTimes(1);
  });

  it.each([new DOMException('Cancelled read', 'AbortError'), new Error('Old read failed')])(
    'does not show an obsolete refresh failure: %s', async (error) => {
      await act(async () => { root.render(<App />); });
      const oldRead = deferred<WorkspaceSnapshot>();
      vi.mocked(cachedWorkspaceSnapshot).mockReturnValueOnce({ fresh: oldRead.promise, revalidated: Promise.resolve(null) });
      await changed();
      current = snapshot('b');
      await changed();
      await act(async () => { oldRead.reject(error); });
      expectPreview('b');
      expect(host.querySelector('.notice.error')).toBeNull();
    }
  );

  it('still reports a failure of the current recovery read', async () => {
    await act(async () => { root.render(<App />); });
    vi.mocked(cachedWorkspaceSnapshot).mockReturnValueOnce({ fresh: Promise.reject(new Error('Current read failed')), revalidated: Promise.resolve(null) });
    await changed();
    expect(host.querySelector('.notice.error')?.textContent).toBe('Current read failed');
  });

  it('does not accept recovery messages from another owner, origin or frame', async () => {
    await act(async () => { root.render(<App />); });
    current = snapshot('b');
    const payload = { type: 'maverick.app.data-changed', owner_app_id: 'website-studio', resource: 'records' };
    await message({ ...payload, owner_app_id: 'storage' });
    await message(payload, 'https://other.invalid');
    await message(payload, window.location.origin, null);
    expect(cachedWorkspaceSnapshot).toHaveBeenCalledTimes(1);
    expectPreview('a');
  });
});
