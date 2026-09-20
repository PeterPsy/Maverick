import { expect, Page } from '@playwright/test';
import { backend } from './backend_fixture';

// The shell uses localhost and CRM uses 127.0.0.1: navigation must work without
// same-origin parent access. Only app-owned test stores are used.
export async function mountSidebarHost(page: Page, dataRoot: string, options: { delayedContext?: boolean; failCounts?: () => boolean } = {}) {
  const port = process.env.CRM_PLAYWRIGHT_PORT || '5187';
  const appOrigin = `http://127.0.0.1:${port}`;
  const shellOrigin = `http://localhost:${port}`;
  // Chromium treats fulfilled shell HTML as public address space. Allow only
  // this test shell to reach its loopback Vite frames; origin isolation stays on.
  await page.context().grantPermissions(['local-network-access'], { origin: shellOrigin });
  backend(dataRoot, { action: 'crm.create_contact', id: 'contact_ada', display_name: 'Ada Example', email: 'ada@example.test' });
  await page.addInitScript(({ appOrigin, shellOrigin }) => {
    if (location.origin === appOrigin) (window as any).__MAVERICK_PLATFORM_ORIGIN__ = shellOrigin;
  }, { appOrigin, shellOrigin });
  await page.route('**/api/apps/crm/backend', async (route) => {
    const body = route.request().postDataJSON();
    if (body.action === 'crm.workspace_view' && body.view === 'sidebar' && options.failCounts?.()) {
      await route.fulfill({ status: 503, json: { message: 'Temporarily unavailable' } });
      return;
    }
    const result = backend(dataRoot, body);
    await route.fulfill({ status: result.status, json: result.body });
  });
  await page.route('**/api/apps/widgets/context/sidebar-test', async (route) => {
    if (options.delayedContext) await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.fulfill({ json: { context: { content: { payload: { active_app_params: { app_page: 'overview' }, is_mobile_layout: false } } } } });
  });
  await page.route(`${shellOrigin}/__crm_test_shell`, (route) => route.fulfill({ contentType: 'text/html', body: `<!doctype html>
    <style>
      * { box-sizing: border-box; } body { margin: 0; background: #070708; display: grid; grid-template-columns: 224px minmax(0,1fr); }
      iframe { border: 0; width: 100%; height: 100dvh; } #sidebar-frame { border-right: 1px solid #262626; }
      #mobile-nav { display: none; }
      @media(max-width:979px) { body { display:block; padding-top:52px; } #mobile-nav { display:block; position:fixed; top:0; height:52px; }
        #crm-frame { height:calc(100dvh - 52px); } #sidebar-frame { position:fixed; inset:0 auto 0 0; width:290px; background:#070708; z-index:2; }
        body:not(.sidebar-open) #sidebar-frame { visibility:hidden; } }
    </style>
    <button id="mobile-nav" onclick="document.body.classList.add('sidebar-open')">Open shell sidebar</button>
    <iframe id="sidebar-frame" title="CRM sidebar" src="${appOrigin}/apps/crm/widgets/crm-sidebar/index.html#context=sidebar-test"></iframe>
    <iframe id="crm-frame" title="CRM workspace" src="${appOrigin}/apps/crm/"></iframe>
    <script>
      const appOrigin = ${JSON.stringify(appOrigin)};
      const sidebar = document.getElementById('sidebar-frame');
      const crm = document.getElementById('crm-frame');
      let params = { app_page: 'overview' };
      window.navigationRequests = [];
      function context() { sidebar.contentWindow.postMessage({ type: 'maverick.widget.context-changed', context: { content: { payload: { active_app_params: params, is_mobile_layout: innerWidth <= 979 } } } }, appOrigin); }
      window.navigateCrm = (next) => { params = next; context(); crm.contentWindow.postMessage({ type: 'maverick.app.navigate', app_id: 'crm', params }, appOrigin); };
      window.refreshCounts = () => sidebar.contentWindow.postMessage({ type: 'maverick.widget.data-changed', owner_app_id: 'crm' }, appOrigin);
      window.addEventListener('resize', context);
      window.addEventListener('message', (event) => {
        if (event.origin !== appOrigin) return;
        const message = event.data;
        if (event.source === sidebar.contentWindow && message.type === 'maverick.widget.ready') context();
        if (event.source === crm.contentWindow && message.type === 'maverick.app.ready') window.navigateCrm(params);
        if ((event.source === sidebar.contentWindow && message.type === 'maverick.widget.open-app') ||
            (event.source === crm.contentWindow && message.type === 'maverick.app.open-app')) {
          window.navigationRequests.push(message);
          window.navigateCrm(message.params);
          document.body.classList.remove('sidebar-open');
        }
      });
    </script>` }));
  await page.goto(`${shellOrigin}/__crm_test_shell`);
  const widget = page.frameLocator('#sidebar-frame');
  const canvas = page.frameLocator('#crm-frame');
  await expect(canvas.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
  return { widget, canvas, appOrigin, shellOrigin };
}
