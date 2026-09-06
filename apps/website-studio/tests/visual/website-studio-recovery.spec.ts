import { expect, test, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import type { PreviewPayload } from '../../frontend/src/api';
import { deferred, preview, snapshot } from '../../frontend/src/App.recovery.fixtures';

// Render the real App, API adapter and nested preview runtime. Only HTTP data
// is simulated; no component, cache, SDK or iframe implementation is mocked.
async function recoveryHarness(page: Page, sameBuild: boolean) {
  const state = {
    version: 'a', reads: 0, builds: 0, errors: [] as string[],
    nextRead: null as Promise<void> | null,
    nextBuild: null as Promise<PreviewPayload> | null
  };
  page.on('pageerror', (error) => { state.errors.push(error.message); });
  // Core resolves this directory URL to index.html; Vite's SPA fallback
  // does not. Serve the unmodified runtime document at its production URL.
  const runtimeHtml = await readFile(new URL('../../frontend/public/preview-runtime/index.html', import.meta.url), 'utf8');
  await page.route('**/apps/website-studio/preview-runtime/**', (request) => request.fulfill({ contentType: 'text/html', body: runtimeHtml }));
  await page.route('**/api/apps/website-studio/backend', async (request) => {
    const body = request.request().postDataJSON() as { action: string; route?: string; preview_id?: string };
    if (body.action === 'workspace_snapshot') {
      const value = snapshot(state.version);
      if (sameBuild) value.project!.latest_preview!.build_id = 'shared-build';
      const gate = state.nextRead;
      state.nextRead = null;
      state.reads += 1;
      if (gate) await gate;
      await request.fulfill({ json: value });
    } else if (body.action === 'build_preview') {
      const pending = state.nextBuild;
      state.nextBuild = null;
      state.builds += 1;
      try {
        const value = pending ? await pending : preview(state.version, body.route);
        if (sameBuild) value.build_id = 'shared-build';
        await request.fulfill({ json: value });
      } catch (error) {
        await request.fulfill({ status: 500, json: { detail: (error as Error).message } });
      }
    } else if (body.action === 'preview_document') {
      await request.fulfill({ json: {
        html: `<!doctype html><html><body><main>${body.preview_id}</main></body></html>`,
        source_map: { preview_id: body.preview_id }
      } });
    } else {
      await request.fulfill({ status: 400, json: { detail: `Unexpected action: ${body.action}` } });
    }
  });
  const message = (data: Record<string, unknown>) => page.evaluate((data) => { window.postMessage(data, window.location.origin); }, data);
  const navigate = (route: string) => message({ type: 'maverick.app.navigate', params: { site_id: 'site', route } });
  const changed = () => message({ type: 'maverick.app.data-changed', owner_app_id: 'website-studio', resource: 'records' });
  const runtime = page.locator('.site-canvas > iframe');
  const document = runtime.contentFrame().locator('#preview').contentFrame().locator('main');
  await page.goto('/apps/website-studio/');
  await expect(document).toHaveText('preview-a-home');
  await expect(page.locator('.preview-loading-state')).toHaveCount(0);
  await runtime.evaluate((node) => { node.setAttribute('data-test-mounted', 'original'); });
  return { state, navigate, changed, runtime, document };
}

for (const sameBuild of [true, false]) {
  test(`navigation during records recovery applies B with ${sameBuild ? 'the same' : 'a new'} runtime build`, async ({ page }) => {
    const { state, navigate, changed, runtime, document } = await recoveryHarness(page, sameBuild);
    await navigate('/about');
    await expect(document).toHaveText('preview-a-about');
    await navigate('/');
    await expect(document).toHaveText('preview-a-home');

    const recovery = deferred<void>();
    state.version = 'b';
    state.nextRead = recovery.promise;
    const originalReads = state.reads;
    await changed();
    await expect.poll(() => state.reads).toBe(originalReads + 1);
    await navigate('/about');
    await expect(document).toHaveText('preview-a-about');
    recovery.resolve();
    await expect(document).toHaveText('preview-b-about');
    await navigate('/');
    await expect(document).toHaveText('preview-b-home');
    await expect(page.locator('.preview-loading-state')).toHaveCount(0);
    await expect(runtime).toHaveAttribute('data-test-mounted', 'original');
    expect(state.reads).toBe(originalReads + 1);
    expect(state.builds).toBe(2);
    expect(state.errors).toEqual([]);
  });

  test(`late navigation HTTP failure cannot cover recovered B with ${sameBuild ? 'the same' : 'a new'} runtime build`, async ({ page }) => {
    const { state, navigate, changed, runtime, document } = await recoveryHarness(page, sameBuild);
    const oldBuild = deferred<PreviewPayload>();
    state.nextBuild = oldBuild.promise;
    await navigate('/about');
    await expect.poll(() => state.builds).toBe(1);
    state.version = 'b';
    await changed();
    await expect(document).toHaveText('preview-b-about');
    await expect(page.locator('.preview-loading-state')).toHaveCount(0);
    const failure = page.waitForResponse((response) => response.url().endsWith('/api/apps/website-studio/backend') && response.status() === 500);
    oldBuild.reject(new Error('Obsolete navigation failed'));
    await (await failure).finished();
    // A subsequent selection fences the failure delivery and verifies that
    // the obsolete request cannot corrupt the warmed snapshot preview.
    await navigate('/');
    await expect(document).toHaveText('preview-b-home');
    await expect(page.locator('.notice')).toHaveCount(0);
    await expect(page.locator('.preview-loading-state')).toHaveCount(0);
    await expect(runtime).toHaveAttribute('data-test-mounted', 'original');
    expect(state.builds).toBe(2);
    expect(state.errors).toEqual([]);
  });
}
