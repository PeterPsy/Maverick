// @vitest-environment happy-dom
import { act } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { setupAppHarness } from './App.testHarness';
import { callBackend, cachedWorkspaceSnapshot, type PreviewPayload, type WorkspaceSnapshot } from './api';
import { deferred, preview, snapshot } from './App.recovery.fixtures';

vi.mock('./api', () => ({
  callBackend: vi.fn(), cachedWorkspaceSnapshot: vi.fn(), invalidateWorkspaceSnapshots: vi.fn()
}));

describe('Website Studio data and selection lifetimes', () => {
  const { state, mount, unmount, frame, expectPreview, message, changed, navigate, useRead } = setupAppHarness();
  const expectNoNotice = () => expect(state.host.querySelector('.notice')).toBeNull();

  it.each(['fresh', 'revalidated'])(
    'applies %s to the latest route/target after multiple warm navigations, without a replacement read', async (phase) => {
      await mount();
      await navigate('/about');
      await navigate('/');
      const recovery = deferred<WorkspaceSnapshot>();
      useRead(phase === 'fresh' ? recovery.promise : Promise.resolve(state.current), phase === 'revalidated' ? recovery.promise : undefined);
      await changed();
      await navigate('/about');
      await navigate('', { app_page: 'pages/home' });
      await navigate('', { app_page: 'routes/about', target_selector: '#team' });
      await act(async () => { state.current = snapshot('b'); recovery.resolve(state.current); });
      expectPreview('b', '/about');
      expect(frame()?.dataset.routeId).toBe('about');
      expect(frame()?.dataset.targetSelector).toBe('#team');
      await navigate('/');
      expectPreview('b');
      expect(cachedWorkspaceSnapshot).toHaveBeenCalledTimes(2);
      expect(callBackend).toHaveBeenCalledTimes(2);
    }
  );

  it.each(['resolve', 'reject'])(
    'does not wait for an initial preview build before revalidation, or publish its late %s', async (settlement) => {
      const build = deferred<PreviewPayload>();
      const revalidation = deferred<WorkspaceSnapshot>();
      useRead(Promise.resolve(snapshot('a', false)), revalidation.promise);
      vi.mocked(callBackend).mockReturnValueOnce(build.promise);
      await mount();
      await act(async () => { revalidation.resolve(snapshot('b')); });
      expectPreview('b');
      await act(async () => {
        if (settlement === 'resolve') build.resolve(preview('a'));
        else build.reject(new Error('Obsolete initial build'));
      });
      expectPreview('b');
      expectNoNotice();
      expect(cachedWorkspaceSnapshot).toHaveBeenCalledTimes(1);
    }
  );

  it.each([false, true])('guards obsolete navigation failures with info_panel=%s while keeping the recovered selection', async (infoPanel) => {
    const oldBuild = deferred<PreviewPayload>();
    vi.mocked(callBackend).mockImplementation(async (body) => {
      if (body.action === 'build_preview') return preview('b', '/about');
      if (body.action === 'site_status') return { site: state.current.project!.site };
      if (body.action === 'list_changes') return { site_id: 'site' };
      throw new Error(`Unexpected action: ${body.action}`);
    }).mockReturnValueOnce(oldBuild.promise);
    await mount();
    await navigate('/about', infoPanel ? { info_panel: '1' } : {});
    state.current = snapshot('b');
    await changed();
    expectPreview('b', '/about');
    await act(async () => { oldBuild.reject(new Error('Obsolete navigation build')); });
    expectPreview('b', '/about');
    expectNoNotice();
    expect(state.host.querySelectorAll('.website-info-panel')).toHaveLength(infoPanel ? 1 : 0);
  });

  it.each([false, true])('still reports current navigation failures with info_panel=%s', async (infoPanel) => {
    await mount();
    vi.mocked(callBackend).mockRejectedValueOnce(new Error('Current navigation failed'));
    await navigate('/about', infoPanel ? { info_panel: '1' } : {});
    expect(state.host.querySelector('.notice.error')?.textContent).toBe('Current navigation failed');
  });

  it('does not clear a newer navigation loader when an obsolete build rejects', async () => {
    state.current.project!.navigation.routes.push({ ...state.current.project!.navigation.routes[0], id: 'contact', route: '/contact' });
    const oldBuild = deferred<PreviewPayload>();
    const currentBuild = deferred<PreviewPayload>();
    vi.mocked(callBackend).mockReturnValueOnce(oldBuild.promise).mockReturnValueOnce(currentBuild.promise);
    await mount();
    await message({ type: 'website-studio.preview.document-ready', owner_app_id: 'website-studio', preview_id: 'preview-a-home' }, window.location.origin, frame()!.contentWindow);
    await navigate('/about');
    await navigate('/contact');
    await act(async () => { oldBuild.reject(new Error('Old About build')); });
    expect(state.host.querySelector('.preview-loading-label')?.textContent).toBe('Caricamento Contact');
    expectNoNotice();
    await act(async () => { currentBuild.resolve(preview('a', '/contact')); });
    expectPreview('a', '/contact');
  });

  it('keeps an info-panel selection and target through recovery without jumping to Home', async () => {
    vi.mocked(callBackend).mockImplementation(async (body) => {
      if (body.action === 'build_preview') return preview(state.current.versions.source_version, String(body.route));
      if (body.action === 'site_status') return { site: state.current.project!.site };
      if (body.action === 'list_changes') return { site_id: 'site' };
      throw new Error(`Unexpected action: ${body.action}`);
    });
    await mount();
    await navigate('/about', { target_selector: '#team' });
    const recovery = deferred<WorkspaceSnapshot>();
    useRead(recovery.promise);
    await changed();
    await message({ type: 'maverick.app.navigate', params: { site_id: 'site', info_panel: '1' } });
    expectPreview('a', '/about');
    await act(async () => { state.current = snapshot('b'); recovery.resolve(state.current); });
    expectPreview('b', '/about');
    expect(frame()?.dataset.targetSelector).toBe('#team');
    expect(state.host.querySelector('.website-info-panel')).not.toBeNull();
  });

  it('reports the current data-read failure even if its starting selection has changed', async () => {
    await mount();
    const recovery = deferred<WorkspaceSnapshot>();
    useRead(recovery.promise);
    await changed();
    await navigate('/about');
    await act(async () => { recovery.reject(new Error('Current recovery failed')); });
    expectPreview('a', '/about');
    expect(state.host.querySelector('.notice.error')?.textContent).toBe('Current recovery failed');
  });

  it.each(['resolve', 'reject'])('ignores a superseded background revalidation that later %ss', async (settlement) => {
    const oldRead = deferred<WorkspaceSnapshot>();
    useRead(Promise.resolve(state.current), oldRead.promise);
    await mount();
    await navigate('/about');
    state.current = snapshot('c');
    await changed();
    await act(async () => {
      if (settlement === 'resolve') oldRead.resolve(snapshot('b'));
      else oldRead.reject(new Error('Obsolete revalidation'));
    });
    expectPreview('c', '/about');
    await navigate('/');
    expectPreview('c');
    expectNoNotice();
    expect(cachedWorkspaceSnapshot).toHaveBeenCalledTimes(2);
  });

  it('observes early revalidation rejection without skipping the valid initial delivery', async () => {
    const initial = deferred<WorkspaceSnapshot>();
    const revalidation = deferred<WorkspaceSnapshot>();
    useRead(initial.promise, revalidation.promise);
    await mount();
    await act(async () => { revalidation.reject(new Error('Revalidation unavailable')); });
    await act(async () => { initial.resolve(snapshot('a')); });
    expectPreview('a');
    expect(state.host.querySelector('.notice.warn')?.textContent).toBe('Revalidation unavailable');
  });

  it('retires both old lifetimes when switching sites', async () => {
    const oldBuild = deferred<PreviewPayload>();
    vi.mocked(callBackend).mockReturnValueOnce(oldBuild.promise);
    await mount();
    await navigate('/about');
    const oldRead = deferred<WorkspaceSnapshot>();
    useRead(oldRead.promise);
    await changed();
    const oldSignal = vi.mocked(cachedWorkspaceSnapshot).mock.calls.at(-1)![2]!.signal;
    state.current = snapshot('c', true, 'other');
    await navigate('/', { site_id: 'other' });
    expect(oldSignal?.aborted).toBe(true);
    expectPreview('c');
    await act(async () => { oldRead.resolve(snapshot('b')); oldBuild.reject(new Error('Old site build')); });
    expectPreview('c');
    expectNoNotice();
    expect(state.host.querySelector('.site-canvas')?.getAttribute('aria-label')).toBe('other');
    await navigate('/', { site_id: 'other' });
    expect(cachedWorkspaceSnapshot).toHaveBeenCalledTimes(3);
  });

  it.each(['new website', 'unmount'])('retires both lifetimes on %s without reviving the old view', async (action) => {
    const oldBuild = deferred<PreviewPayload>();
    vi.mocked(callBackend).mockReturnValueOnce(oldBuild.promise);
    await mount();
    await navigate('/about');
    const oldRead = deferred<WorkspaceSnapshot>();
    useRead(oldRead.promise);
    await changed();
    const oldSignal = vi.mocked(cachedWorkspaceSnapshot).mock.calls.at(-1)![2]!.signal;
    if (action === 'unmount') unmount();
    else await message({ type: 'maverick.app.navigate', params: { new_website_request_id: 'new' } });
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => { oldRead.resolve(snapshot('b')); oldBuild.reject(new Error('Retired view build')); });
    expect(frame()).toBeNull();
    expectNoNotice();
    if (action === 'new website') expect(state.host.querySelector('.connection-guide')).not.toBeNull();
  });
});
