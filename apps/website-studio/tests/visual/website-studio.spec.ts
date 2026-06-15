import { expect, test, type Page } from '@playwright/test';

type Box = { x: number; y: number; width: number; height: number };
type MockState = { backendActions: string[]; changedFilesCount: number; previewRuntimeRequests: number };
type MockOptions = { delayedAction?: string; delayMs?: number; emptySites?: boolean; withoutLatestPreview?: boolean };
type MockPreview = {
  id: string;
  site_id: string;
  route: string;
  page_id: string;
  build_id: string;
  runtime_kind: string;
  runtime_status: string;
  status: string;
  preview_url: string;
  warnings: string[];
  missing_requirements: string[];
};

const SITE_ID = 'site_giuntitrail';
const PREVIEW_ID = 'preview_giuntitrail_ready';

test.describe('Website Studio visual smoke', () => {
  test('shows chat guidance when no website is connected', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1180, height: 820 });
    await installWebsiteStudioMocks(page, { emptySites: true });

    await page.goto('/');

    const guide = page.locator('.connection-guide');
    await expect(guide).toBeVisible();
    await expect(guide).toContainText('Ask an agent to connect a website');
    await expect(guide).toContainText('Drive ZIP');
    await expect(guide).toContainText('GitHub with Vault');
    await expect(page.locator('.import-button')).toHaveCount(0);
    await expect(page.locator('.git-import')).toHaveCount(0);

    const screenshot = await page.screenshot({ fullPage: false });
    expect(screenshot.length).toBeGreaterThan(6_000);
    await testInfo.attach('website-studio-empty-guide.png', {
      body: screenshot,
      contentType: 'image/png'
    });
  });

  test('shows a shell-style preview loading state while preview data resolves', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1180, height: 820 });
    await installWebsiteStudioMocks(page, { delayedAction: 'build_preview', delayMs: 1_600, withoutLatestPreview: true });

    await page.goto('/');

    const loading = page.locator('.preview-loading-state');
    await expect(loading).toBeVisible();
    await expect(loading).toContainText('Preview is loading');
    await expect(page.locator('.site-empty')).toHaveCount(0);

    const screenshot = await page.screenshot({ fullPage: false });
    expect(screenshot.length).toBeGreaterThan(4_000);
    await testInfo.attach('website-studio-preview-loading.png', {
      body: screenshot,
      contentType: 'image/png'
    });

    await expect(page.locator('.site-canvas iframe')).toBeVisible();
    await expect(loading).toHaveCount(0);
  });

  for (const viewport of [
    { name: 'desktop', width: 1440, height: 920 },
    { name: 'mobile', width: 390, height: 844 }
  ]) {
    test(`renders a nonblank ready preview on ${viewport.name}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await installWebsiteStudioMocks(page);

      await page.goto('/');
      await openSite(page);

      const canvas = page.locator('.site-canvas');
      const iframe = page.locator('.site-canvas iframe');
      const infoPanel = page.locator('.website-info-panel');

      await expect(canvas).toBeVisible();
      await expect(iframe).toBeVisible();
      await expect(iframe).toHaveAttribute('data-preview-url', /client_version=website-studio-preview-frame-v8/);
      await expect(page.locator('.preview-status')).toHaveCount(0);
      await expect(page.locator('.site-status-panel')).toHaveCount(0);
      await expect(infoPanel).toHaveCount(0);

      const frame = await iframe.elementHandle();
      const contentFrame = await frame?.contentFrame();
      expect(contentFrame).not.toBeNull();
      await expect(contentFrame!.locator('[data-testid="runtime-preview"]')).toContainText('Giuntitrail');

      await emitShellMessage(page, {
        type: 'maverick.app.navigate',
        params: { site_id: SITE_ID, app_page: 'info', website_info: '1' }
      });

      await expect(infoPanel).toBeVisible();
      await expect(infoPanel).toContainText('Giuntitrail');
      await expect(infoPanel).toContainText('ready');
      await expect(infoPanel).toContainText('published');

      const canvasBox = await requiredBox(canvas, 'site canvas');
      const iframeBox = await requiredBox(iframe, 'preview iframe');
      const infoPanelBox = await requiredBox(infoPanel, 'website info panel');

      expect(iframeBox.width).toBeGreaterThan(280);
      expect(iframeBox.height).toBeGreaterThan(420);
      expect(isInside(infoPanelBox, canvasBox)).toBe(true);

      await page.locator('.website-info-close').click();
      await expect(infoPanel).toBeHidden();

      const screenshot = await page.screenshot({ fullPage: false });
      expect(screenshot.length).toBeGreaterThan(viewport.name === 'mobile' ? 8_000 : 12_000);
      await testInfo.attach(`website-studio-${viewport.name}.png`, {
        body: screenshot,
        contentType: 'image/png'
      });
    });
  }

  test('responds to mounted shell navigation and data change events', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1180, height: 820 });
    const mockState = await installWebsiteStudioMocks(page);

    await page.goto('/');
    await openSite(page);

    const iframe = page.locator('.site-canvas iframe');
    await expect(iframe).toBeVisible();
    await expect(page.locator('.preview-status')).toHaveCount(0);
    await expect(page.locator('.site-status-panel')).toHaveCount(0);
    const initialRuntimeRequests = mockState.previewRuntimeRequests;
    const initialBuildPreviewCount = mockState.backendActions.filter((action) => action === 'build_preview').length;
    const initialFrameHandle = await iframe.elementHandle();
    expect(initialFrameHandle).not.toBeNull();
    await initialFrameHandle!.evaluate((node) => node.setAttribute('data-warm-frame-marker', 'initial'));

    await expect(async () => {
      await emitShellMessage(page, {
        type: 'maverick.app.navigate',
        params: { site_id: SITE_ID, app_page: 'routes/route_about' }
      });
      await expect(iframe).toHaveAttribute('data-route-id', 'route_about', { timeout: 750 });
      await expect(iframe).toHaveAttribute('data-preview-url', /route=%2Fabout/, { timeout: 750 });
    }).toPass({ timeout: 6_000 });
    await expect.poll(() => mockState.previewRuntimeRequests, { timeout: 750 }).toBe(initialRuntimeRequests);
    await expect(iframe).toHaveAttribute('data-warm-frame-marker', 'initial');
    const frameAfterRoute = await (await iframe.elementHandle())?.contentFrame();
    expect(frameAfterRoute).not.toBeNull();
    await expect(frameAfterRoute!.locator('[data-testid="runtime-preview"]')).toContainText('About Giuntitrail');

    await expect(async () => {
      await emitShellMessage(page, {
        type: 'maverick.app.navigate',
        params: { site_id: SITE_ID, app_page: 'components/component_cta', page_id: 'page_home', route: '/', target_selector: '.cta' }
      });
      await expect(iframe).toHaveAttribute('data-component-id', 'component_cta', { timeout: 750 });
      await expect(iframe).toHaveAttribute('data-target-selector', '.cta', { timeout: 750 });
      await expect(iframe).toHaveAttribute('data-preview-url', /target_selector=\.cta/, { timeout: 750 });
    }).toPass({ timeout: 6_000 });
    expect(mockState.previewRuntimeRequests).toBe(initialRuntimeRequests);
    expect(mockState.backendActions.filter((action) => action === 'build_preview').length).toBe(initialBuildPreviewCount + 1);

    await emitShellMessage(page, {
      type: 'maverick.app.navigate',
      params: { site_id: SITE_ID, app_page: 'info', website_info: '1' }
    });
    const infoPanel = page.locator('.website-info-panel');
    await expect(infoPanel).toBeVisible();
    await expect(infoPanel).toContainText('Giuntitrail');

    mockState.changedFilesCount = 1;
    const actionsBeforeRefresh = mockState.backendActions.length;
    await expect(async () => {
      await emitShellMessage(page, { type: 'maverick.app.data-changed', owner_app_id: 'website-studio' });
      await expect.poll(() => mockState.backendActions.length, { timeout: 750 }).toBeGreaterThan(actionsBeforeRefresh);
    }).toPass({ timeout: 6_000 });

    await expect(infoPanel.locator('.website-info-metric').filter({ hasText: 'changed' }).locator('strong')).toHaveText('1');
    expect(mockState.backendActions.filter((action) => action === 'list_changes').length).toBeGreaterThanOrEqual(2);

    const canvasBox = await requiredBox(page.locator('.site-canvas'), 'site canvas');
    const iframeBox = await requiredBox(iframe, 'preview iframe');
    const infoPanelBox = await requiredBox(infoPanel, 'website info panel');

    expect(isInside(iframeBox, canvasBox)).toBe(true);
    expect(isInside(infoPanelBox, canvasBox)).toBe(true);

    const screenshot = await page.screenshot({ fullPage: false });
    expect(screenshot.length).toBeGreaterThan(12_000);
    await testInfo.attach('website-studio-shell-events.png', {
      body: screenshot,
      contentType: 'image/png'
    });
  });

  test('does not open the removed sidebar fullscreen preview flow', async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    await installWebsiteStudioMocks(page);

    await page.goto('/');
    await openSite(page);

    const fullscreenPreview = page.locator('.website-fullscreen-preview');
    const inlinePreview = page.locator('.site-canvas iframe');
    await expect(inlinePreview).toBeVisible();

    await emitShellMessage(page, {
      type: 'maverick.app.navigate',
      params: { site_id: SITE_ID, app_page: 'preview/fullscreen', fullscreen_preview: '1' }
    });

    await expect(fullscreenPreview).toHaveCount(0);
    await expect(page.locator('.website-fullscreen-preview-close')).toHaveCount(0);
    await expect(inlinePreview).toBeVisible();
    await expect(inlinePreview).toHaveAttribute('src', /preview-runtime/);
  });

  test('sidebar visual navigation opens pages and component targets', async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    await installWebsiteStudioMocks(page);
    await page.goto('/apps/website-studio/widgets/website-studio-sitemap-sidebar/');
    await page.evaluate(() => {
      (window as unknown as { __websiteStudioMessages?: unknown[] }).__websiteStudioMessages = [];
      window.addEventListener('message', (event) => {
        (window as unknown as { __websiteStudioMessages?: unknown[] }).__websiteStudioMessages?.push(event.data);
      });
    });

    await emitShellMessage(page, {
      type: 'maverick.widget.context-changed',
      context: { content: { payload: { active_app_params: { site_id: SITE_ID } } } }
    });

    await expect(page.locator('.website-studio-tree-trigger').filter({ hasText: 'Giuntitrail' }).first()).toBeVisible();
    await expect(page.getByText('Backend and config')).toHaveCount(0);
    await expect(page.getByText('README.md')).toHaveCount(0);
    await expect(page.getByText('No observed sections')).toHaveCount(0);
    await expect(page.getByText('Rendered routes')).toHaveCount(0);

    await page.getByText('Home').click();
    await expect.poll(async () => openAppMessages(page).then((messages) => messages.some((message) => message.params?.app_page === 'pages/page_home' && message.params?.route === '/')), { timeout: 2_000 }).toBe(true);

    const homeTrigger = page.locator('.website-studio-tree-trigger').filter({ hasText: 'Home' }).first();
    await homeTrigger.locator('.website-studio-tree-expander').click();
    const componentsTrigger = page.locator('.website-studio-tree-trigger').filter({ hasText: 'Components' }).first();
    await componentsTrigger.locator('.website-studio-tree-expander').click();
    await expect(page.getByText('Call to action')).toBeVisible();
    await page.getByText('Call to action').click();
    await expect.poll(async () => openAppMessages(page).then((messages) => messages.some((message) => (
      message.params?.app_page === 'components/component_cta' &&
      message.params?.route === '/' &&
      message.params?.component_id === 'component_cta' &&
      message.params?.target_selector === '.cta'
    ))), { timeout: 2_000 }).toBe(true);
  });
});

test.describe('Website Studio preview runtime', () => {
  test('hot navigation reuses gateway URLs for shared assets', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 860 });
    let documentRequests = 0;
    const gatewayRequests: string[] = [];

    await page.route('**/api/apps/website-studio/backend', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}') as { action?: string; preview_id?: string };
      expect(body.action).toBe('preview_document');
      documentRequests += 1;
      const previewId = body.preview_id || 'preview_hot_a';
      const routePath = previewId.endsWith('_b') ? '/about' : '/';
      const suffix = previewId.endsWith('_b') ? 'b' : 'a';
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          preview: { id: previewId, status: 'ready' },
          html: `<!doctype html>
            <html>
              <body style="margin:0">
                <main data-testid="runtime-preview">
                  <span data-testid="route">${routePath}</span>
                  <img data-testid="logo" src="assets/logo.svg" alt="">
                </main>
              </body>
            </html>`,
          source_map: {
            preview_id: previewId,
            route: routePath,
            asset_refs: ['assets/logo.svg'],
            asset_gateway: {
              'assets/logo.svg': `/api/apps/website-studio/backend/file/gw_logo_${suffix}`
            }
          }
        })
      });
    });

    await page.route('**/api/apps/website-studio/backend/file/gw_logo_*', async (route) => {
      gatewayRequests.push(new URL(route.request().url()).pathname);
      await route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        headers: { 'Cache-Control': 'public, max-age=3600' },
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" fill="#1d7f64"/></svg>'
      });
    });

    await page.goto('/apps/website-studio/preview-runtime/index.html?preview_id=preview_hot_a&route=%2F');

    const previewFrame = page.frameLocator('#preview');
    await expect(previewFrame.locator('[data-testid="route"]')).toContainText('/');
    await expect(previewFrame.locator('[data-testid="logo"]')).toHaveAttribute('src', /gw_logo_a/);
    await previewFrame.locator('body').evaluate(() => {
      (window as unknown as { __websiteStudioRouteMarker?: string }).__websiteStudioRouteMarker = 'home-stayed-mounted';
      document.body.setAttribute('data-route-marker', 'home-stayed-mounted');
    });

    await page.evaluate(() => {
      window.postMessage(
        {
          type: 'website-studio.preview.navigate',
          owner_app_id: 'website-studio',
          preview_id: 'preview_hot_b',
          route: '/about',
          preview_url: '/apps/website-studio/preview-runtime/?preview_id=preview_hot_b&route=%2Fabout'
        },
        window.location.origin
      );
    });

    await expect(previewFrame.locator('[data-testid="route"]')).toContainText('/about');
    await expect(previewFrame.locator('[data-testid="logo"]')).toHaveAttribute('src', /gw_logo_a/);
    expect(documentRequests).toBe(2);
    expect(gatewayRequests.some((path) => path.endsWith('gw_logo_b'))).toBe(false);

    await page.evaluate(() => {
      window.postMessage(
        {
          type: 'website-studio.preview.navigate',
          owner_app_id: 'website-studio',
          preview_id: 'preview_hot_a',
          route: '/',
          preview_url: '/apps/website-studio/preview-runtime/?preview_id=preview_hot_a&route=%2F'
        },
        window.location.origin
      );
    });

    await expect(previewFrame.locator('[data-testid="route"]')).toContainText('/');
    await expect(previewFrame.locator('body')).toHaveAttribute('data-route-marker', 'home-stayed-mounted');
    await expect.poll(async () => previewFrame.locator('body').evaluate(() => {
      return (window as unknown as { __websiteStudioRouteMarker?: string }).__websiteStudioRouteMarker || '';
    }), { timeout: 1_000 }).toBe('home-stayed-mounted');
    expect(documentRequests).toBe(2);
  });

  test('mounts the document before slow lazy media finishes loading', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 860 });
    const previewId = 'preview_slow_assets';
    let slowVideoRequested = false;
    let directMediaRequests = 0;
    let brokerMediaRequests = 0;
    let fileGatewayRequests = 0;
    const mediaUrl = (path: string) =>
      `__WEBSITE_STUDIO_PREVIEW_ORIGIN__/api/apps/website-studio/backend/media?preview_id=${previewId}&path=${encodeURIComponent(path)}`;

    await page.route('**/api/apps/website-studio/backend', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}') as { action?: string };
      expect(body.action).toBe('preview_document');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          preview: { id: previewId, status: 'ready' },
          html: `<!doctype html>
            <html>
              <head>
                <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob: __WEBSITE_STUDIO_PREVIEW_MEDIA_SOURCE__; media-src data: blob: __WEBSITE_STUDIO_PREVIEW_MEDIA_SOURCE__; font-src data: blob: __WEBSITE_STUDIO_PREVIEW_MEDIA_SOURCE__; style-src 'unsafe-inline' blob: __WEBSITE_STUDIO_PREVIEW_MEDIA_SOURCE__; script-src 'unsafe-inline' blob: __WEBSITE_STUDIO_PREVIEW_MEDIA_SOURCE__; connect-src 'none'; frame-ancestors 'self'; form-action 'none'; base-uri 'none'">
                <style>
                  @font-face { font-family: PreviewRuntime; src: url("${mediaUrl('assets/fonts/preview.woff2')}") format("woff2"); }
                  body { margin: 0; font-family: PreviewRuntime, system-ui, sans-serif; background: #f7f7f2; }
                  main { min-height: 100vh; display: grid; place-content: center; background-image: url("${mediaUrl('assets/images/hero.webp')}"); }
                  img { width: 96px; height: 96px; object-fit: cover; }
                </style>
              </head>
              <body>
                <main data-testid="runtime-preview">
                  <h1>Giuntitrail</h1>
                  <img data-testid="eager-image" src="${mediaUrl('assets/images/logo.webp')}" alt="">
                  <img data-testid="lazy-image" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==" data-src="${mediaUrl('assets/images/lazy.webp')}" alt="">
                  <video data-testid="slow-video" data-src="${mediaUrl('assets/video/slow.mp4')}" muted playsinline></video>
                </main>
                <script>
                  console.warn('preview console ready');
                  window.setTimeout(() => {
                    const image = document.querySelector('[data-testid="lazy-image"]');
                    image.src = image.dataset.src;
                    image.removeAttribute('data-src');
                    const script = document.createElement('script');
                    script.src = "${mediaUrl('assets/js/analytics-tracking.js')}";
                    document.body.appendChild(script);
                  }, 50);
                </script>
              </body>
            </html>`
          ,
          source_map: {
            preview_id: previewId,
            route: '/',
            source_files: ['index.html', 'assets/site.css'],
            asset_refs: ['assets/fonts/preview.woff2', 'assets/images/logo.webp', 'assets/images/hero.webp', 'assets/video/slow.mp4'],
            asset_gateway: {
              'assets/fonts/preview.woff2': '/api/apps/website-studio/backend/file/gw_font',
              'assets/images/logo.webp': '/api/apps/website-studio/backend/file/gw_logo',
              'assets/images/hero.webp': '/api/apps/website-studio/backend/file/gw_hero',
              'assets/images/lazy.webp': '/api/apps/website-studio/backend/file/gw_lazy',
              'assets/js/analytics-tracking.js': '/api/apps/website-studio/backend/file/gw_script',
              'assets/video/slow.mp4': '/api/apps/website-studio/backend/file/gw_slow_video'
            },
            selector_hints: [{ selector: '[data-testid]', token: 'runtime-preview', source_files: ['index.html'], confidence: 'token_match' }]
          }
        })
      });
    });

    await page.route('**/api/apps/website-studio/backend/file/gw_*', async (route) => {
      fileGatewayRequests += 1;
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('gw_slow_video')) {
        slowVideoRequested = true;
        await delay(4_000);
        await route.fulfill({ status: 206, contentType: 'video/mp4', body: Buffer.from([0]) });
        return;
      }
      if (path.endsWith('gw_font')) {
        await route.fulfill({ status: 200, contentType: 'font/woff2', body: Buffer.from([0]) });
        return;
      }
      if (path.endsWith('gw_script')) {
        await route.fulfill({ status: 200, contentType: 'text/javascript', body: 'window.__dynamicLocalScriptLoaded = true;' });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="#f72585"/></svg>'
      });
    });

    await page.route('**/api/apps/website-studio/backend/media?**', async (route) => {
      const url = new URL(route.request().url());
      const path = url.searchParams.get('path') || '';
      const isBrokered = route.request().headers()['x-website-studio-preview-broker'] === '1';
      if (isBrokered) brokerMediaRequests += 1;
      else directMediaRequests += 1;
      if (path.endsWith('slow.mp4')) {
        slowVideoRequested = true;
        await delay(4_000);
        await route.fulfill({ status: 200, contentType: 'video/mp4', body: Buffer.from([0]) });
        return;
      }
      if (path.endsWith('.woff2')) {
        await route.fulfill({ status: 200, contentType: 'font/woff2', body: Buffer.from([0]) });
        return;
      }
      if (path.endsWith('.js')) {
        await route.fulfill({ status: 200, contentType: 'text/javascript', body: 'window.__dynamicLocalScriptLoaded = true;' });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="#f72585"/></svg>'
      });
    });

    const startedAt = Date.now();
    await page.goto(`/apps/website-studio/preview-runtime/index.html?preview_id=${previewId}&target_selector=main&target_id=component_main&target_kind=component`);

    const previewFrame = page.frameLocator('#preview');
    await expect(previewFrame.locator('[data-testid="runtime-preview"]')).toContainText('Giuntitrail', { timeout: 1_500 });
    expect(Date.now() - startedAt).toBeLessThan(2_000);
    expect(slowVideoRequested).toBe(false);

    const imageSrc = await previewFrame.locator('[data-testid="eager-image"]').getAttribute('src');
    expect(imageSrc).toContain('/api/apps/website-studio/backend/file/gw_logo');
    await expect.poll(async () => previewFrame.locator('[data-testid="eager-image"]').evaluate((node) => {
      const image = node as HTMLImageElement;
      return image.complete && image.naturalWidth > 2 && image.naturalHeight > 2;
    }), { timeout: 3_000 }).toBe(true);
    await expect.poll(async () => previewFrame.locator('[data-testid="lazy-image"]').evaluate((node) => {
      const image = node as HTMLImageElement;
      return image.complete && image.naturalWidth > 2 && image.naturalHeight > 2 && !image.src.includes('R0lGODlhAQABAIAAAAAA');
    }), { timeout: 3_000 }).toBe(true);
    await expect.poll(async () => previewFrame.locator('main').evaluate((element) => getComputedStyle(element).backgroundImage)).toContain('/api/apps/website-studio/backend/file/gw_hero');
    await expect.poll(async () => previewFrame.locator('body').evaluate(() => {
      return (window as unknown as { __dynamicLocalScriptLoaded?: boolean }).__dynamicLocalScriptLoaded === true;
    }), { timeout: 3_000 }).toBe(true);
    expect(fileGatewayRequests).toBeGreaterThanOrEqual(4);
    expect(directMediaRequests).toBe(0);
    expect(brokerMediaRequests).toBe(0);

    await expect.poll(async () => page.evaluate(() => {
      const report = (window as unknown as { __WEBSITE_STUDIO_PREVIEW_REPORT__?: { report?: { console_log?: { text?: string }[] } } }).__WEBSITE_STUDIO_PREVIEW_REPORT__;
      return report?.report?.console_log?.some((item) => item.text?.includes('preview console ready')) || false;
    }), { timeout: 3_000 }).toBe(true);

    const runtimeReport = await page.evaluate(() => {
      return (window as unknown as { __WEBSITE_STUDIO_PREVIEW_REPORT__?: { report?: Record<string, unknown> } }).__WEBSITE_STUDIO_PREVIEW_REPORT__?.report || {};
    });
    expect(runtimeReport.nonblank).toBe(true);
    expect((runtimeReport.dom as { snapshot: { tag: string; computed: { fontFamily?: string } }[] }).snapshot.some((item) => item.tag === 'main')).toBe(true);
    expect((runtimeReport.fonts as { status: string }).status).toMatch(/loaded|loading/);
    await expect.poll(async () => page.evaluate(() => {
      const reports = (window as unknown as { __WEBSITE_STUDIO_PREVIEW_REPORTS__?: { report?: { asset_broker?: { cache_size?: number } } }[] }).__WEBSITE_STUDIO_PREVIEW_REPORTS__ || [];
      return Math.max(...reports.map((entry) => entry.report?.asset_broker?.cache_size || 0), 0);
    }), { timeout: 3_000 }).toBe(0);
    await expect.poll(async () => page.evaluate(() => {
      const reports = (window as unknown as { __WEBSITE_STUDIO_PREVIEW_REPORTS__?: { report?: { asset_coverage?: { images?: { src?: string }[] } } }[] }).__WEBSITE_STUDIO_PREVIEW_REPORTS__ || [];
      return reports.some((entry) => entry.report?.asset_coverage?.images?.some((item) => item.src?.includes('/api/apps/website-studio/backend/file/gw_')));
    }), { timeout: 3_000 }).toBe(true);
    await expect.poll(async () => page.evaluate(() => {
      const reports = (window as unknown as { __WEBSITE_STUDIO_PREVIEW_REPORTS__?: { report?: { asset_coverage?: { placeholder_images?: unknown[]; broken_images?: unknown[] } } }[] }).__WEBSITE_STUDIO_PREVIEW_REPORTS__ || [];
      const latest = [...reports].reverse().find((entry) => entry.report?.asset_coverage)?.report?.asset_coverage;
      return (latest?.placeholder_images?.length || 0) + (latest?.broken_images?.length || 0);
    }), { timeout: 3_000 }).toBe(0);
    expect((runtimeReport.source_map as { asset_refs: string[] }).asset_refs).toContain('assets/fonts/preview.woff2');
    expect((runtimeReport.target as { found?: boolean; selector?: string }).selector).toBe('main');
    expect((runtimeReport.target as { found?: boolean; selector?: string }).found).toBe(true);
  });
});

async function installWebsiteStudioMocks(page: Page, options: MockOptions = {}): Promise<MockState> {
  const state: MockState = { backendActions: [], changedFilesCount: 0, previewRuntimeRequests: 0 };

  await page.route('**/api/apps/website-studio/backend', async (route) => {
    const body = JSON.parse(route.request().postData() || '{}') as Record<string, unknown> & { action?: string };
    const action = body.action || 'sites_list';
    state.backendActions.push(action);
    const response = backendResponse(action, body, state, options);
    if (options.delayedAction === action) {
      await delay(options.delayMs || 500);
    }
    await route.fulfill({
      status: response.status,
      contentType: 'application/json',
      body: JSON.stringify(response.body)
    });
  });

  await page.route('**/apps/website-studio/preview-runtime/**', async (route) => {
    state.previewRuntimeRequests += 1;
    const requested = new URL(route.request().url());
    const routePath = requested.searchParams.get('route') || '/';
    const heading = routePath === '/about' ? 'About Giuntitrail' : 'Giuntitrail';
    await route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: `<!doctype html>
        <html>
          <head>
            <style>
              html, body {
                margin: 0;
                min-height: 100%;
                background: #f7f7f2;
                color: #172019;
                font: 16px system-ui, sans-serif;
              }
              main {
                min-height: 100vh;
                display: grid;
                align-content: center;
                gap: 18px;
                padding: 12vw;
              }
              h1 { margin: 0; font-size: clamp(38px, 8vw, 96px); }
              p { margin: 0; max-width: 42rem; line-height: 1.55; }
            </style>
          </head>
              <body>
                <main data-testid="runtime-preview">
                  <h1>${heading}</h1>
                  <p>Runtime preview ready for ${routePath}.</p>
                </main>
                <script>
                  const renderRoute = (routePath) => {
                    const cleanRoute = routePath || '/';
                    document.querySelector('h1').textContent = cleanRoute === '/about' ? 'About Giuntitrail' : 'Giuntitrail';
                    document.querySelector('p').textContent = 'Runtime preview ready for ' + cleanRoute + '.';
                  };
                  window.addEventListener('message', (event) => {
                    const data = event.data || {};
                    if (data.type !== 'website-studio.preview.navigate') return;
                    renderRoute(data.route || '/');
                  });
                </script>
              </body>
            </html>`
    });
  });

  return state;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function openSite(page: Page, params: Record<string, string> = {}): Promise<void> {
  await emitShellMessage(page, {
    type: 'maverick.app.navigate',
    params: { site_id: SITE_ID, ...params }
  });
}

async function emitShellMessage(page: Page, payload: Record<string, unknown>): Promise<void> {
  await page.evaluate((message) => {
    window.dispatchEvent(
      new MessageEvent('message', {
        origin: window.location.origin,
        source: window,
        data: message
      })
    );
    window.postMessage(message, window.location.origin);
  }, payload);
}

async function openAppMessages(page: Page): Promise<Array<{ params?: Record<string, string>; type?: string }>> {
  return page.evaluate(() => {
    const messages = (window as unknown as { __websiteStudioMessages?: Array<{ params?: Record<string, string>; type?: string }> }).__websiteStudioMessages || [];
    return messages.filter((message) => message?.type === 'maverick.widget.open-app');
  });
}

function backendResponse(action: string, body: Record<string, unknown>, state: MockState, options: MockOptions): { status: number; body: Record<string, unknown> } {
  const requestedRoute = typeof body.route === 'string' && body.route ? body.route : '/';
  const preview = previewForRoute(requestedRoute);
  const latestPreview = previewForRoute('/');
  const workingDiff = state.changedFilesCount
    ? [{ id: 'diff_about', path: 'about.html', status: 'modified', diff_summary: 'about.html updated' }]
    : [];
  const changedTone = state.changedFilesCount ? 'modified' : 'clean';
  const site = {
    id: SITE_ID,
    display_name: 'Giuntitrail',
    slug: 'giuntitrail',
    status: 'draft',
    source_provider: 'git',
    active_revision_id: 'rev_working',
    published_revision_id: 'rev_published',
    is_active: true
  };

  function sitemapBody() {
    return {
      site_id: SITE_ID,
      items: [{ id: 'page_home', site_id: SITE_ID, route: '/', title: 'Home', kind: 'html', status: 'active', source_files: ['index.php'] }],
      routes: [
        { id: 'route_home', site_id: SITE_ID, route: '/', page_id: 'page_home', kind: 'php', status: 'rendered', source_files: ['index.php'] },
        { id: 'route_about', site_id: SITE_ID, route: '/about', kind: 'php', status: 'rendered', source_files: ['about.php'] }
      ],
      assets: [{ id: 'asset_logo', site_id: SITE_ID, path: 'assets/logo.svg', kind: 'image', status: 'active' }]
    };
  }

  function navigationBody() {
    return {
      site_id: SITE_ID,
      model: 'visual_navigation.v1',
      site,
      pages: [
        {
          id: 'page_home',
          route: '/',
          route_id: 'route_home',
          title: 'Home',
          status: 'rendered',
          changed: Boolean(state.changedFilesCount),
          sections: [{ id: 'section_hero', kind: 'section', route: '/', page_id: 'page_home', selector: '#hero', anchor: '#hero', label: 'Hero' }],
          anchors: [],
          components: [{ id: 'component_cta', kind: 'component', route: '/', page_id: 'page_home', selector: '.cta', label: 'Call to action', confidence: 'token_match' }],
          warnings: []
        }
      ],
      routes: [
        {
          id: 'route_about',
          route: '/about',
          title: '/about',
          status: 'rendered',
          sections: [],
          anchors: [],
          components: [],
          warnings: []
        }
      ],
      components: [{ id: 'component_cta', kind: 'component', route: '/', page_id: 'page_home', selector: '.cta', label: 'Call to action', confidence: 'token_match' }],
      warnings: [],
      status: {
        runtime_kind: 'php',
        runtime_status: 'ready',
        latest_build_id: 'build_ready',
        latest_build_status: 'passed',
        latest_preview_id: latestPreview.id,
        changed_files_count: state.changedFilesCount
      },
      inventory_summary: { page_count: 1, route_count: 2, asset_count: 1, source_inventory_hidden: true }
    };
  }

  switch (action) {
    case 'bootstrap':
      if (options.emptySites) {
        return {
          status: 200,
          body: {
            sites: [],
            active_site_id: '',
            persisted_active_site_id: '',
            sitemap: { site_id: '', items: [], routes: [], assets: [] },
            latest_preview: null
          }
        };
      }
      return {
        status: 200,
        body: {
          sites: [site],
          active_site_id: SITE_ID,
          persisted_active_site_id: SITE_ID,
          sitemap: { ...sitemapBody(), assets: [] },
          latest_preview: options.withoutLatestPreview ? null : latestPreview
        }
      };
    case 'sites_list':
      if (options.emptySites) return { status: 200, body: { items: [] } };
      return { status: 200, body: { items: [site] } };
    case 'sitemap':
      return { status: 200, body: sitemapBody() };
    case 'navigation_analyze':
      return { status: 200, body: navigationBody() };
    case 'site_status':
      return {
        status: 200,
        body: {
          site,
          page_count: 1,
          route_count: 2,
          asset_count: 1,
          changed_files_count: state.changedFilesCount,
          active_revision_id: 'rev_working',
          published_revision_id: 'rev_published',
          runtime_kind: 'php',
          runtime_status: 'ready',
          missing_requirements: [],
          runtime: {
            runtime_kind: 'php',
            runtime_status: 'ready',
            missing_requirements: [],
            latest_build: { id: 'build_ready', status: 'passed' },
            latest_preview: latestPreview
          },
          latest_build_id: 'build_ready',
          latest_preview_id: latestPreview.id
        }
      };
    case 'list_changes':
      return {
        status: 200,
        body: {
          site_id: SITE_ID,
          working_diff: workingDiff,
          publish_requests: [{ id: 'pub_ready', status: 'published', build_id: 'build_ready', diff_summary: changedTone }],
          approval_events: [{ id: 'appr_ready', status: 'approved' }],
          builds: [{ id: 'build_ready', status: 'passed' }],
          deployments: [{ id: 'deploy_ready', status: 'published', mode: 'maverick_managed_static' }]
        }
      };
    case 'preview_document':
      return {
        status: 200,
        body: {
          preview: latestPreview,
          html: '<!doctype html><html><body><main data-testid="runtime-preview"><h1>Giuntitrail</h1><p>Runtime preview ready.</p></main></body></html>'
        }
      };
    case 'build_preview':
      return {
        status: 200,
        body: {
          ...preview,
          preview_id: preview.id,
          environment_id: 'env_preview',
          route_id: requestedRoute === '/about' ? 'route_about' : 'route_home',
          html: `<!doctype html><html><body><main data-testid="runtime-preview">${requestedRoute === '/about' ? 'About Giuntitrail' : 'Giuntitrail'}</main></body></html>`
        }
      };
    default:
      return { status: 400, body: { error: 'unsupported_action', detail: `Unsupported action ${action}` } };
  }
}

function previewForRoute(routePath: string): MockPreview {
  const suffix = routePath === '/about' ? 'about' : 'home';
  return {
    id: `${PREVIEW_ID}_${suffix}`,
    site_id: SITE_ID,
    route: routePath,
    page_id: routePath === '/' ? 'page_home' : '',
    build_id: 'build_ready',
    runtime_kind: 'php',
    runtime_status: 'ready',
    status: 'ready',
    preview_url: `/apps/website-studio/preview-runtime/?preview_id=${PREVIEW_ID}_${suffix}&route=${encodeURIComponent(routePath)}`,
    warnings: [],
    missing_requirements: []
  };
}

async function requiredBox(locator: ReturnType<Page['locator']>, label: string): Promise<Box> {
  const box = await locator.boundingBox();
  expect(box, `${label} should have a layout box`).not.toBeNull();
  return box!;
}

function isInside(inner: Box, outer: Box): boolean {
  return inner.x >= outer.x && inner.y >= outer.y && inner.x + inner.width <= outer.x + outer.width && inner.y + inner.height <= outer.y + outer.height;
}
