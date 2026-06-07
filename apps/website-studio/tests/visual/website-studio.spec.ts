import { expect, test, type Page } from '@playwright/test';

type Box = { x: number; y: number; width: number; height: number };

const SITE_ID = 'site_giuntitrail';
const PREVIEW_ID = 'preview_giuntitrail_ready';
const PREVIEW_URL = `/apps/website-studio/preview-runtime/?preview_id=${PREVIEW_ID}&route=%2F`;

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
});

async function installWebsiteStudioMocks(page: Page): Promise<void> {
  await page.route('**/api/apps/website-studio/backend', async (route) => {
    const body = JSON.parse(route.request().postData() || '{}') as { action?: string };
    const action = body.action || 'sites_list';
    const response = backendResponse(action);
    await route.fulfill({
      status: response.status,
      contentType: 'application/json',
      body: JSON.stringify(response.body)
    });
  });

  await page.route('**/apps/website-studio/preview-runtime/**', async (route) => {
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
              <h1>Giuntitrail</h1>
              <p>Runtime preview ready for the selected Website Studio site.</p>
            </main>
          </body>
        </html>`
    });
  });
}

function backendResponse(action: string): { status: number; body: Record<string, unknown> } {
  const preview = {
    id: PREVIEW_ID,
    site_id: SITE_ID,
    route: '/',
    page_id: 'page_home',
    build_id: 'build_ready',
    runtime_kind: 'php',
    status: 'ready',
    preview_url: PREVIEW_URL,
    warnings: [],
    missing_requirements: []
  };
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

  switch (action) {
    case 'sites_list':
      return { status: 200, body: { items: [site] } };
    case 'sitemap':
      return {
        status: 200,
        body: {
          site_id: SITE_ID,
          items: [{ id: 'page_home', site_id: SITE_ID, route: '/', title: 'Home', kind: 'html', status: 'active', source_files: ['index.php'] }],
          routes: [{ id: 'route_home', site_id: SITE_ID, route: '/', page_id: 'page_home', kind: 'php', status: 'rendered', source_files: ['index.php'] }],
          assets: [{ id: 'asset_logo', site_id: SITE_ID, path: 'assets/logo.svg', kind: 'image', status: 'active' }]
        }
      };
    case 'site_status':
      return {
        status: 200,
        body: {
          site,
          page_count: 1,
          route_count: 1,
          asset_count: 1,
          changed_files_count: 0,
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
            latest_preview: preview
          },
          latest_build_id: 'build_ready',
          latest_preview_id: PREVIEW_ID
        }
      };
    case 'list_changes':
      return {
        status: 200,
        body: {
          site_id: SITE_ID,
          working_diff: [],
          publish_requests: [{ id: 'pub_ready', status: 'published', build_id: 'build_ready' }],
          approval_events: [{ id: 'appr_ready', status: 'approved' }],
          builds: [{ id: 'build_ready', status: 'passed' }],
          deployments: [{ id: 'deploy_ready', status: 'published', mode: 'maverick_managed_static' }]
        }
      };
    case 'preview_document':
      return {
        status: 200,
        body: {
          preview,
          html: '<!doctype html><html><body><main data-testid="runtime-preview"><h1>Giuntitrail</h1><p>Runtime preview ready.</p></main></body></html>'
        }
      };
    case 'build_preview':
      return {
        status: 200,
        body: {
          preview_id: PREVIEW_ID,
          site_id: SITE_ID,
          environment_id: 'env_preview',
          route: '/',
          page_id: 'page_home',
          route_id: 'route_home',
          runtime_kind: 'php',
          runtime_status: 'ready',
          preview_url: PREVIEW_URL,
          build_id: 'build_ready',
          missing_requirements: [],
          warnings: [],
          html: '<!doctype html><html><body><main data-testid="runtime-preview">Giuntitrail</main></body></html>'
        }
      };
    default:
      return { status: 400, body: { error: 'unsupported_action', detail: `Unsupported action ${action}` } };
  }
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
