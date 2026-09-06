import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { preview, snapshot } from '../../frontend/src/App.recovery.fixtures';

// Render the real App, API adapter and nested preview runtime. Only HTTP data
// is simulated; no component, cache, SDK or iframe implementation is mocked.
for (const sameBuild of [true, false]) {
  test(`records recovery replaces visible preview documents with ${sameBuild ? 'the same' : 'a new'} runtime build`, async ({ page }) => {
    let version = 'a';
    let reads = 0;
    const actions: string[] = [];
    const errors: string[] = [];
    page.on('pageerror', (error) => { errors.push(error.message); });
    // Core resolves this directory URL to index.html; Vite's SPA fallback
    // does not. Serve the unmodified runtime document at its production URL.
    const runtimeHtml = await readFile(new URL('../../frontend/public/preview-runtime/index.html', import.meta.url), 'utf8');
    await page.route('**/apps/website-studio/preview-runtime/**', (request) => request.fulfill({ contentType: 'text/html', body: runtimeHtml }));
    await page.route('**/api/apps/website-studio/backend', async (request) => {
      const body = request.request().postDataJSON() as { action: string; route?: string; preview_id?: string };
      actions.push(body.action);
      if (body.action === 'workspace_snapshot') {
        reads += 1;
        const value = snapshot(version);
        if (sameBuild) value.project!.latest_preview!.build_id = 'shared-build';
        await request.fulfill({ json: value });
      } else if (body.action === 'build_preview') {
        const value = preview(version, body.route);
        if (sameBuild) value.build_id = 'shared-build';
        await request.fulfill({ json: value });
      } else if (body.action === 'preview_document') {
        await request.fulfill({ json: {
          html: `<!doctype html><html><body><main>${body.preview_id}</main></body></html>`,
          source_map: { preview_id: body.preview_id }
        } });
      } else {
        await request.fulfill({ status: 400, json: { detail: `Unexpected action: ${body.action}` } });
      }
    });

    await page.goto('/apps/website-studio/');
    const runtime = page.locator('.site-canvas > iframe');
    const document = runtime.contentFrame().locator('#preview').contentFrame().locator('main');
    await expect(document).toHaveText('preview-a-home');
    await runtime.evaluate((node) => { node.setAttribute('data-test-mounted', 'original'); });
    const originalReads = reads;
    const navigate = async (route: string) => {
      await page.evaluate((route) => {
        window.postMessage({ type: 'maverick.app.navigate', params: { site_id: 'site', route } }, window.location.origin);
      }, route);
    };
    await navigate('/about');
    await expect(document).toHaveText('preview-a-about');
    await navigate('/');
    await expect(document).toHaveText('preview-a-home');

    version = 'b';
    await page.evaluate(() => {
      window.postMessage({ type: 'maverick.app.data-changed', owner_app_id: 'website-studio', resource: 'records' }, window.location.origin);
    });
    await expect(document).toHaveText('preview-b-home');
    await expect(runtime).toHaveAttribute('data-test-mounted', 'original');
    expect(reads).toBe(originalReads + 1);
    await navigate('/about');
    await expect(document).toHaveText('preview-b-about');
    await expect(page.locator('.preview-loading-state')).toHaveCount(0);
    await expect(runtime).toHaveAttribute('data-test-mounted', 'original');
    expect(actions.filter((action) => action === 'build_preview')).toHaveLength(2);
    expect(errors).toEqual([]);
  });
}
