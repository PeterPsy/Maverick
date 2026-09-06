import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, vi } from 'vitest';
import { App } from './App';
import { callBackend, cachedWorkspaceSnapshot, type WorkspaceSnapshot } from './api';
import { preview, snapshot } from './App.recovery.fixtures';

export function setupAppHarness() {
  let host: HTMLDivElement;
  const state = { current: snapshot('a'), get host() { return host; } };
  let root: Root;
  let mounted: boolean;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    host = document.createElement('div');
    root = createRoot(host);
    mounted = true;
    state.current = snapshot('a');
    vi.mocked(cachedWorkspaceSnapshot).mockImplementation(() => ({ fresh: Promise.resolve(state.current), revalidated: Promise.resolve(null) }));
    vi.mocked(callBackend).mockImplementation(async (body) => {
      if (body.action !== 'build_preview') throw new Error(`Unexpected action: ${body.action}`);
      return preview(state.current.versions.source_version, String(body.route), String(body.site_id));
    });
  });

  function unmount() {
    if (mounted) act(() => root.unmount());
    mounted = false;
  }
  afterEach(() => { unmount(); vi.resetAllMocks(); });

  async function mount() { await act(async () => { root.render(<App />); }); }
  function frame() { return state.host.querySelector<HTMLIFrameElement>('.site-canvas iframe'); }
  function expectPreview(version: string, route = '/') {
    expect(frame()?.dataset.previewUrl).toContain(preview(version, route).preview_url);
  }
  async function message(data: Record<string, unknown>, origin = window.location.origin, source: Window | null = window) {
    await act(async () => { window.dispatchEvent(new MessageEvent('message', { data, origin, source })); });
  }
  function changed(resource = 'records') {
    return message({ type: 'maverick.app.data-changed', owner_app_id: 'website-studio', resource });
  }
  function navigate(route: string, params: Record<string, string> = {}) {
    return message({ type: 'maverick.app.navigate', params: { site_id: 'site', route, ...params } });
  }
  function useRead(fresh: Promise<WorkspaceSnapshot>, revalidated: Promise<WorkspaceSnapshot | null> = Promise.resolve(null)) {
    vi.mocked(cachedWorkspaceSnapshot).mockReturnValueOnce({ fresh, revalidated });
  }

  return { state, mount, unmount, frame, expectPreview, message, changed, navigate, useRead };
}
