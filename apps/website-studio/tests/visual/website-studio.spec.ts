import { expect, test, type Page } from '@playwright/test';

type Box = { x: number; y: number; width: number; height: number };
type MockState = { backendActions: string[]; changedFilesCount: number };
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
  for (const viewport of [
    { name: 'desktop', width: 1440, height: 920 },
    { name: 'mobile', width: 390, height: 844 }
  ]) {
    test(`renders a nonblank ready preview on ${viewport.name}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await installWebsiteStudioMocks(page);

      await page.goto('/');

      const canvas = page.locator('.site-canvas');
      const iframe = page.locator('.site-canvas iframe');
      const previewStatus = page.locator('.preview-status');
      const siteStatus = page.locator('.site-status-panel');

      await expect(canvas).toBeVisible();
      await expect(iframe).toBeVisible();
      await expect(previewStatus).toContainText('ready');
      await expect(siteStatus).toContainText('Giuntitrail');
      await expect(siteStatus).toContainText('published');

      const frame = await iframe.elementHandle();
      const contentFrame = await frame?.contentFrame();
      expect(contentFrame).not.toBeNull();
      await expect(contentFrame!.locator('[data-testid="runtime-preview"]')).toContainText('Giuntitrail');

      const canvasBox = await requiredBox(canvas, 'site canvas');
      const iframeBox = await requiredBox(iframe, 'preview iframe');
      const previewStatusBox = await requiredBox(previewStatus, 'preview status');
      const siteStatusBox = await requiredBox(siteStatus, 'site status');

      expect(iframeBox.width).toBeGreaterThan(280);
      expect(iframeBox.height).toBeGreaterThan(420);
      expect(isInside(previewStatusBox, canvasBox)).toBe(true);
      expect(isInside(siteStatusBox, canvasBox)).toBe(true);
      expect(intersects(previewStatusBox, siteStatusBox)).toBe(false);

      const screenshot = await page.screenshot({ fullPage: false });
      expect(screenshot.length).toBeGreaterThan(12_000);
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

    const iframe = page.locator('.site-canvas iframe');
    const siteStatus = page.locator('.site-status-panel');
    await expect(iframe).toBeVisible();
    await expect(siteStatus).toContainText('Giuntitrail');

    await expect(async () => {
      await emitShellMessage(page, {
        type: 'maverick.app.navigate',
        params: { site_id: SITE_ID, app_page: 'routes/route_about' }
      });
      await expect(iframe).toHaveAttribute('data-route-id', 'route_about', { timeout: 750 });
      await expect(iframe).toHaveAttribute('src', /route=%2Fabout/, { timeout: 750 });
    }).toPass({ timeout: 6_000 });

    mockState.changedFilesCount = 1;
    const actionsBeforeRefresh = mockState.backendActions.length;
    await expect(async () => {
      await emitShellMessage(page, { type: 'maverick.app.data-changed', owner_app_id: 'website-studio' });
      await expect.poll(() => mockState.backendActions.length, { timeout: 750 }).toBeGreaterThan(actionsBeforeRefresh);
    }).toPass({ timeout: 6_000 });

    await expect(siteStatus.locator('.site-status-metric').filter({ hasText: 'changed' }).locator('strong')).toHaveText('1');
    expect(mockState.backendActions.filter((action) => action === 'list_changes').length).toBeGreaterThanOrEqual(2);

    const canvasBox = await requiredBox(page.locator('.site-canvas'), 'site canvas');
    const iframeBox = await requiredBox(iframe, 'preview iframe');
    const previewStatusBox = await requiredBox(page.locator('.preview-status'), 'preview status');
    const siteStatusBox = await requiredBox(siteStatus, 'site status');

    expect(isInside(iframeBox, canvasBox)).toBe(true);
    expect(isInside(previewStatusBox, canvasBox)).toBe(true);
    expect(isInside(siteStatusBox, canvasBox)).toBe(true);
    expect(intersects(previewStatusBox, siteStatusBox)).toBe(false);

    const screenshot = await page.screenshot({ fullPage: false });
    expect(screenshot.length).toBeGreaterThan(12_000);
    await testInfo.attach('website-studio-shell-events.png', {
      body: screenshot,
      contentType: 'image/png'
    });
  });

  test('opens and closes the private fullscreen website preview', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    await installWebsiteStudioMocks(page);

    await page.goto('/');

    const fullscreenPreview = page.locator('.website-fullscreen-preview');
    const fullscreenFrame = page.locator('.website-fullscreen-preview iframe');
    await expect(page.locator('.site-canvas iframe')).toBeVisible();

    await emitShellMessage(page, {
      type: 'maverick.app.navigate',
      params: { site_id: SITE_ID, app_page: 'preview/fullscreen', fullscreen_preview: '1' }
    });

    await expect(fullscreenPreview).toBeVisible();
    await expect(fullscreenFrame).toBeVisible();
    await expect(fullscreenFrame).toHaveAttribute('src', /preview-runtime/);
    await expect(page.locator('.website-fullscreen-preview-close')).toBeVisible();

    const previewBox = await requiredBox(fullscreenPreview, 'fullscreen preview');
    const frameBox = await requiredBox(fullscreenFrame, 'fullscreen preview iframe');
    expect(previewBox.width).toBe(1366);
    expect(previewBox.height).toBe(900);
    expect(frameBox.width).toBe(1366);
    expect(frameBox.height).toBe(900);

    const screenshot = await page.screenshot({ fullPage: false });
    expect(screenshot.length).toBeGreaterThan(12_000);
    await testInfo.attach('website-studio-fullscreen-preview.png', {
      body: screenshot,
      contentType: 'image/png'
    });

    await page.locator('.website-fullscreen-preview-close').click();
    await expect(fullscreenPreview).toBeHidden();
  });
});

async function installWebsiteStudioMocks(page: Page): Promise<MockState> {
  const state: MockState = { backendActions: [], changedFilesCount: 0 };

  await page.route('**/api/apps/website-studio/backend', async (route) => {
    const body = JSON.parse(route.request().postData() || '{}') as Record<string, unknown> & { action?: string };
    const action = body.action || 'sites_list';
    state.backendActions.push(action);
    const response = backendResponse(action, body, state);
    await route.fulfill({
      status: response.status,
      contentType: 'application/json',
      body: JSON.stringify(response.body)
    });
  });

  await page.route('**/apps/website-studio/preview-runtime/**', async (route) => {
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
          </body>
        </html>`
    });
  });

  return state;
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

function backendResponse(action: string, body: Record<string, unknown>, state: MockState): { status: number; body: Record<string, unknown> } {
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

  switch (action) {
    case 'sites_list':
      return { status: 200, body: { items: [site] } };
    case 'sitemap':
      return { status: 200, body: sitemapBody() };
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

function intersects(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}
