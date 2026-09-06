// @vitest-environment happy-dom
import { act } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { setupAppHarness } from './App.testHarness';
import { callBackend, cachedWorkspaceSnapshot, type PreviewPayload, type WorkspaceSnapshot } from './api';
import { deferred, preview, snapshot } from './App.recovery.fixtures';

vi.mock('./api', () => ({
  callBackend: vi.fn(), cachedWorkspaceSnapshot: vi.fn(), invalidateWorkspaceSnapshots: vi.fn()
}));

describe('Website Studio snapshot recovery', () => {
  const { state, mount, frame, expectPreview, message, changed, navigate } = setupAppHarness();

  it.each(['records', 'source', 'working-state', 'navigation', 'preview', 'activity', 'settings', 'view-selection'])(
    'reconciles the preview with the new snapshot after %s, regardless of alias order', async (resource) => {
      await mount();
      expectPreview('a');
      state.current = snapshot('b');
      await changed(resource);
      expect(cachedWorkspaceSnapshot).toHaveBeenCalledTimes(2);
      expectPreview('b');
      expect(callBackend).not.toHaveBeenCalled();
    }
  );

  it('keeps the preview frame mounted during recovery and invalidates other warmed routes', async () => {
    await mount();
    const originalFrame = frame();
    await navigate('/about');
    expectPreview('a', '/about');
    await navigate('/');
    expectPreview('a');
    expect(callBackend).toHaveBeenCalledTimes(1);

    state.current = snapshot('b');
    await changed();
    expectPreview('b');
    expect(frame()).toBe(originalFrame);
    await navigate('/about');
    expectPreview('b', '/about');
    expect(callBackend).toHaveBeenCalledTimes(2);
    expect(frame()).toBe(originalFrame);
  });

  it('accepts recovery data after navigating to a warmed route while its snapshot is pending', async () => {
    await mount();
    await navigate('/about');
    await navigate('/');
    const recovery = deferred<WorkspaceSnapshot>();
    vi.mocked(cachedWorkspaceSnapshot).mockReturnValueOnce({ fresh: recovery.promise, revalidated: Promise.resolve(null) });
    await changed();
    await navigate('/about');
    expectPreview('a', '/about');
    await act(async () => { state.current = snapshot('b'); recovery.resolve(state.current); });
    expectPreview('b', '/about');
    await navigate('/');
    expectPreview('b');
  });

  it('does not let a rejected pre-recovery navigation build report an error over B', async () => {
    const oldBuild = deferred<PreviewPayload>();
    vi.mocked(callBackend).mockReturnValueOnce(oldBuild.promise);
    await mount();
    await navigate('/about');
    state.current = snapshot('b');
    await changed();
    await navigate('/');
    expectPreview('b');
    await act(async () => { oldBuild.reject(new Error('Obsolete navigation failed')); });
    expectPreview('b');
    expect(state.host.querySelector('.notice.error')).toBeNull();
  });

  it('preserves warmed route reuse when a reread has the same snapshot revision', async () => {
    await mount();
    await navigate('/about');
    await navigate('/');
    state.current = snapshot('a'); // New object, unchanged content revision.
    await changed();
    await navigate('/about');
    expectPreview('a', '/about');
    expect(callBackend).toHaveBeenCalledTimes(1);
  });

  it('prefers the snapshot-supplied preview over RAM within the same cache generation', async () => {
    await mount();
    state.current = snapshot('a');
    state.current.project!.latest_preview = snapshot('b').project!.latest_preview;
    await changed();
    expectPreview('b');
    expect(callBackend).not.toHaveBeenCalled();
  });

  it('updates derived previews when a stale initial snapshot revalidates without another event', async () => {
    const revalidation = deferred<WorkspaceSnapshot | null>();
    vi.mocked(cachedWorkspaceSnapshot).mockReturnValueOnce({ fresh: Promise.resolve(state.current), revalidated: revalidation.promise });
    await mount();
    expectPreview('a');
    await act(async () => {
      state.current = snapshot('b');
      revalidation.resolve(state.current);
    });
    expectPreview('b');
    expect(callBackend).not.toHaveBeenCalled();
  });

  it('never reuses a pre-recovery preview build or lets its completion erase the replacement request', async () => {
    const oldBuild = deferred<PreviewPayload>();
    const newBuild = deferred<PreviewPayload>();
    vi.mocked(callBackend).mockReturnValueOnce(oldBuild.promise).mockReturnValueOnce(newBuild.promise);
    await mount();
    await navigate('/about');
    expect(callBackend).toHaveBeenCalledTimes(1);

    state.current = snapshot('b');
    await changed();
    // Recovery preserves the pending About selection rather than jumping
    // to Home. Explicitly select the snapshot-supplied Home preview first.
    await navigate('/');
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
    await mount();
    state.current = snapshot('b', false);
    await changed();
    expectPreview('b');
    expect(callBackend).toHaveBeenCalledTimes(1);
  });

  it('refreshes visible site details along with a recovered preview', async () => {
    vi.mocked(callBackend).mockImplementation(async (body) => {
      if (body.action === 'site_status') return { site: state.current.project!.site, changed_files_count: state.current.versions.source_version === 'a' ? 0 : 1 };
      if (body.action === 'list_changes') return { site_id: 'site', working_diff: [], builds: [], deployments: [], publish_requests: [], approval_events: [] };
      throw new Error(`Unexpected action: ${body.action}`);
    });
    await mount();
    await message({ type: 'maverick.app.navigate', params: { site_id: 'site', info_panel: '1' } });
    const changedFiles = () => Array.from(state.host.querySelectorAll('.website-info-metric'))
      .find((metric) => metric.querySelector('span')?.textContent === 'changed')?.querySelector('strong')?.textContent;
    expect(changedFiles()).toBe('0');
    state.current = snapshot('b');
    await changed();
    expectPreview('b');
    expect(changedFiles()).toBe('1');
  });

  it('ignores late snapshots from an obsolete refresh, including their cache invalidation', async () => {
    await mount();
    const oldRead = deferred<WorkspaceSnapshot>();
    vi.mocked(cachedWorkspaceSnapshot).mockReturnValueOnce({ fresh: oldRead.promise, revalidated: Promise.resolve(null) });
    await changed();
    state.current = snapshot('b');
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
      await mount();
      const oldRead = deferred<WorkspaceSnapshot>();
      vi.mocked(cachedWorkspaceSnapshot).mockReturnValueOnce({ fresh: oldRead.promise, revalidated: Promise.resolve(null) });
      await changed();
      state.current = snapshot('b');
      await changed();
      await act(async () => { oldRead.reject(error); });
      expectPreview('b');
      expect(state.host.querySelector('.notice.error')).toBeNull();
    }
  );

  it('still reports a failure of the current recovery read', async () => {
    await mount();
    vi.mocked(cachedWorkspaceSnapshot).mockReturnValueOnce({ fresh: Promise.reject(new Error('Current read failed')), revalidated: Promise.resolve(null) });
    await changed();
    expect(state.host.querySelector('.notice.error')?.textContent).toBe('Current read failed');
  });

  it('does not accept recovery messages from another owner, origin or frame', async () => {
    await mount();
    state.current = snapshot('b');
    const payload = { type: 'maverick.app.data-changed', owner_app_id: 'website-studio', resource: 'records' };
    await message({ ...payload, owner_app_id: 'storage' });
    await message(payload, 'https://other.invalid');
    await message(payload, window.location.origin, null);
    expect(cachedWorkspaceSnapshot).toHaveBeenCalledTimes(1);
    expectPreview('a');
  });
});
