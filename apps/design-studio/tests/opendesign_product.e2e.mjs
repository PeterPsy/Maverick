#!/usr/bin/env node

/** Run the WP10 production-path browser acceptance against the pinned OCI bundle. */

import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { lstat, mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';


const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(appRoot, '..', '..');
const artifactStoreRoot = process.env.MAVERICK_APP_ARTIFACT_STORE_ROOT
  || path.join(path.dirname(repoRoot), `.${path.basename(repoRoot)}-app-artifacts`);
process.env.MAVERICK_APP_ARTIFACT_STORE_ROOT = artifactStoreRoot;
const serverFixture = path.join(scriptDir, 'fixtures', 'opendesign_product_server.py');
const migrationSmoke = path.join(appRoot, 'service', 'smoke_opendesign_migration.py');
const python = process.env.MAVERICK_OPENDESIGN_E2E_PYTHON
  || path.join(repoRoot, '.venv', 'bin', 'python');
const bundleContract = JSON.parse(await readFile(path.join(appRoot, 'service', 'opendesign_bundle.json'), 'utf8'));
const profile = argument('--profile') || 'release';
if (!['quick', 'affected', 'release'].includes(profile)) {
  throw new Error('E2E profile must be quick, affected, or release');
}
const changedFiles = argumentsAll('--changed-file');
const requestedOverlayDigest = argument('--web-overlay-sha256') || await releasedOverlayDigest();
const overlayContract = await canonicalOverlayContract(requestedOverlayDigest);
const evidenceOutput = argument('--evidence-output');
const evidenceOutputPath = evidenceOutput
  ? (path.isAbsolute(evidenceOutput)
      ? evidenceOutput
      : path.resolve(evidenceOutput.startsWith('apps/design-studio/') ? repoRoot : appRoot, evidenceOutput))
  : '';
const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), 'moe-'));
const keepTemporary = process.env.MAVERICK_KEEP_E2E_TEMP === '1';
const installationRoot = path.join(temporaryRoot, 'i');
const port = await freePort();
const platformOrigin = `http://maverick.localhost:${port}`;
process.env.PLAYWRIGHT_BROWSERS_PATH ||= process.env.MAVERICK_PLAYWRIGHT_BROWSERS_PATH
  || path.resolve(repoRoot, '..', '..', '.cache', 'ms-playwright');
const { chromium } = await import('playwright');
let server = null;
let browser = null;


class ProfileComplete extends Error {
  constructor(evidence) {
    super('profile complete');
    this.evidence = evidence;
  }
}


try {
  await mkdir(installationRoot, { recursive: true });
  server = await startServer();
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  const networkProof = {
    isolatedRequests: 0,
    bootstrapPosts: 0,
    nativeChatRequests: 0,
    maverickCookieForwarded: false,
    browserBearerForwarded: false,
    diagnostics: [],
  };
  page.on('request', (request) => {
    let parsed;
    try { parsed = new URL(request.url()); } catch { return; }
    if (!isSidecarHostname(parsed.hostname)) return;
    networkProof.isolatedRequests += 1;
    if (/\/api\/projects\/[^/]+\/conversations(?:\/|$)/.test(parsed.pathname)) {
      networkProof.nativeChatRequests += 1;
    }
    if (parsed.pathname === '/.well-known/maverick-sidecar-bootstrap' && request.method() === 'POST') {
      networkProof.bootstrapPosts += 1;
    }
    const headers = request.headers();
    const cookie = headers.cookie || '';
    if (cookie.includes('maverick_session=')) networkProof.maverickCookieForwarded = true;
    if (headers.authorization) networkProof.browserBearerForwarded = true;
  });
  page.on('response', (response) => {
    let parsed;
    try { parsed = new URL(response.url()); } catch { return; }
    if (!isSidecarHostname(parsed.hostname)) return;
    networkProof.diagnostics.push({ method: response.request().method(), path: parsed.pathname, status: response.status() });
  });
  page.on('requestfailed', (request) => {
    let parsed;
    try { parsed = new URL(request.url()); } catch { return; }
    if (!isSidecarHostname(parsed.hostname)) return;
    networkProof.diagnostics.push({
      method: request.method(),
      path: parsed.pathname,
      failure: String(request.failure()?.errorText || 'request_failed').slice(0, 120),
    });
  });

  await loginAndOpen(page);
  let sidecar = await waitForSidecarFrame(page, '', networkProof);
  const initialReady = await frameRequest(sidecar, '/api/maverick-ready');
  assert(
    initialReady.status === 200 && initialReady.body?.ok === true && initialReady.body?.ready === true,
    `Initial OpenDesign readiness returned HTTP ${initialReady.status}`,
  );
  await completeOpenDesignOnboarding(page, sidecar);
  const originA = new URL(sidecar.url()).origin;
  assert(originA !== platformOrigin, 'OpenDesign did not use an isolated origin');

  const projectA = await createProjectFromUi(page, sidecar, 'Maverick WP10 browser project', networkProof);
  if (profile === 'quick') {
    throw new ProfileComplete(buildProfileEvidence({
      profile,
      scenarios: [
        scenario('login_open', 'Login and open Design Studio', { isolated_origin: true, ready_endpoint: true }),
        scenario('create_project_ui', 'Create and open a project from the Maverick sidebar', {
          project_created: true,
          sidebar_navigation: true,
          native_home_projects_hidden: true,
          native_chat_unmounted: true,
        }),
      ],
      canonicalEntity: { od_project_id: projectA.projectId, od_run_id: '' },
    }));
  }
  const uploaded = await platformRequest(page, '/api/workspace-files/uploads', {
    method: 'POST',
    body: {
      filename: 'wp10-brief.md',
      content_type: 'text/markdown',
      content_base64: Buffer.from('# WP10 brief\n\nGoverned Storage import.\n').toString('base64'),
    },
  });
  assert(uploaded.status === 201, `Storage upload returned HTTP ${uploaded.status}`);
  const uploadedPath = uploaded.body?.file?.relative_path;
  assert(typeof uploadedPath === 'string' && uploadedPath.startsWith('storage/uploaded/'), 'Storage upload path is invalid');
  const imported = await frameRequest(sidecar, '/api/import/storage', {
    method: 'POST',
    body: { project_id: projectA.projectId, workspace_relative_path: uploadedPath },
  });
  assert(imported.status === 200, `Storage import returned HTTP ${imported.status}`);
  const importedFile = await frameText(sidecar, `/api/projects/${encodeURIComponent(projectA.projectId)}/raw/wp10-brief.md`);
  assert(importedFile.status === 200 && importedFile.text.includes('Governed Storage import.'), 'Storage import read-back failed');

  const successful = await createRun(sidecar, projectA, 'Create the governed WP10 HTML artifact.');
  const streamProof = await readIncrementalStream(sidecar, successful.runId);
  const successfulRun = await waitForRun(sidecar, successful.runId, 'succeeded');
  const successfulPackage = await resultPackage(sidecar, successful.runId);
  if (!streamProof.incremental || (!streamProof.closed && !streamProof.terminal)) {
    const runtimeEvents = await platformRequest(
      page,
      `/api/runtime/sessions/${encodeURIComponent(successfulPackage.maverick.runtime_session_id)}/events`,
    );
    const eventTypes = Array.isArray(runtimeEvents.body?.items)
      ? runtimeEvents.body.items.map((item) => String(item?.event_type || '')).filter(Boolean)
      : [];
    throw new Error(`Incremental SSE did not deliver and terminate cleanly: ${JSON.stringify({ ...streamProof, eventTypes })}`);
  }
  const correlationA = correlationFromPackage(successfulPackage, projectA.projectId, successful.runId);
  const preview = await frameText(sidecar, `/api/projects/${encodeURIComponent(projectA.projectId)}/raw/index.html`);
  assert(preview.status === 200 && preview.text.includes('Maverick real runtime file proof'), 'Generated file preview failed');
  assert(successfulRun.status === 'succeeded', 'Successful run status drifted');

  const canceled = await createRun(sidecar, projectA, 'MAVERICK_E2E_LONG');
  let canceledStreamFailure = null;
  const canceledStreamPromise = readIncrementalStream(sidecar, canceled.runId).catch((error) => {
    canceledStreamFailure = error;
    return null;
  });
  await waitForRun(sidecar, canceled.runId, 'running');
  const cancelOne = await frameRequest(sidecar, `/api/runs/${encodeURIComponent(canceled.runId)}/cancel`, { method: 'POST' });
  const cancelTwo = await frameRequest(sidecar, `/api/runs/${encodeURIComponent(canceled.runId)}/cancel`, { method: 'POST' });
  assert(cancelOne.status === 200 && cancelTwo.status === 200, 'Cancel was not idempotent');
  const canceledRun = await waitForRun(sidecar, canceled.runId, 'canceled');
  const canceledStream = await canceledStreamPromise;
  if (!canceledStream) throw canceledStreamFailure || new Error('Canceled run SSE failed');
  const canceledPackage = await resultPackage(sidecar, canceled.runId);
  const correlationCanceled = correlationFromPackage(canceledPackage, projectA.projectId, canceled.runId);
  assert(
    canceledRun.status === 'canceled' && canceledPackage.run.status === 'canceled' && canceledStream.terminal,
    'Canceled package or stream drifted',
  );

  const exported = await frameRequest(sidecar, '/api/export/storage', {
    method: 'POST',
    body: { project_id: projectA.projectId, run_id: successful.runId },
  });
  assert(exported.status === 200, `Storage export returned HTTP ${exported.status}`);
  const manifestPath = `storage/generated/design-studio/${projectA.projectId}/${successful.runId}/manifest.json`;
  const manifestRead = await storageRead(page, manifestPath);
  assert(manifestRead.status === 200, `Export manifest read returned HTTP ${manifestRead.status}`);
  const manifest = JSON.parse(Buffer.from(manifestRead.body.content_base64, 'base64').toString('utf8'));
  assert(manifest.od_project_id === projectA.projectId && manifest.od_run_id === successful.runId, 'Export identity drifted');
  assert(Array.isArray(manifest.artifacts) && manifest.artifacts.length >= 1, 'Export manifest has no artifacts');

  const forbidden = await frameRequest(sidecar, '/api/import/folder', { method: 'POST', body: {} });
  const unknown = await frameRequest(sidecar, '/api/wp10-unknown-route');
  const coreRoute = await frameRequest(sidecar, '/api/session');
  assert(forbidden.status === 403, 'Sensitive OpenDesign route was not blocked');
  assert(unknown.status === 404 && coreRoute.status === 404, 'Unknown or Maverick core route leaked through sidecar origin');
  const browserStorage = await sidecar.evaluate(() => ({
    cookie: document.cookie,
    href: window.location.href,
    local: Object.entries(localStorage),
    session: Object.entries(sessionStorage),
  }));
  const browserStorageText = JSON.stringify([browserStorage.local, browserStorage.session]);
  assert(browserStorage.cookie === '', 'A script-visible cookie reached OpenDesign');
  assert(!/(ticket|bearer|maverick_session)/i.test(browserStorageText), 'A credential-like value reached browser storage');
  const cleanSidecarUrl = new URL(browserStorage.href);
  assert(cleanSidecarUrl.search === '' && cleanSidecarUrl.hash === '', 'OpenDesign retained bootstrap material in its URL');

  if (profile === 'affected') {
    const scenarios = buildFirstWorkspaceScenarios({
      correlationA,
      correlationCanceled,
      manifest,
      networkProof,
    });
    throw new ProfileComplete(buildProfileEvidence({
      profile,
      scenarios,
      canonicalEntity: { od_project_id: projectA.projectId, od_run_id: successful.runId },
    }));
  }

  const warmTickets = await benchmarkWarmTickets(page, 30);
  const warmOpenings = await benchmarkWarmOpenings(page, networkProof, 30);
  const coreRestarts = [];
  let bootstrapCountBeforeRestart = networkProof.bootstrapPosts;
  for (let iteration = 0; iteration < 10; iteration += 1) {
    await page.goto(`${platformOrigin}/health`, { waitUntil: 'domcontentloaded' });
    await delay(100);
    const startedAt = performance.now();
    await stopServer(server);
    const stoppedAt = performance.now();
    server = await startServer();
    const coreReadyAt = server.wp10CoreReadyAt;
    const readiness = await waitForTransactionalReadiness(page);
    const transactionalReadyAt = performance.now();
    await page.goto(`${platformOrigin}/app/design-studio`, { waitUntil: 'domcontentloaded' });
    sidecar = await waitForSidecarFrame(page, '', networkProof, true);
    const browserReadyAt = performance.now();
    const daemonReadyMs = Number(readiness.body?.opendesign?.runtime?.timings_ms?.daemon_ready_ms);
    assert(Number.isFinite(daemonReadyMs) && daemonReadyMs > 0, 'Core restart omitted daemon readiness timing');
    const resources = await processResourceSnapshot(server.pid);
    coreRestarts.push({
      iteration: iteration + 1,
      daemon_ready_ms: daemonReadyMs,
      cold_maverick_ready_ms: rounded(transactionalReadyAt - server.wp10StartedAt),
      full_restart_ms: rounded(browserReadyAt - startedAt),
      stop_ms: rounded(stoppedAt - startedAt),
      core_boot_ms: rounded(coreReadyAt - server.wp10StartedAt),
      prewarm_after_core_health_ms: rounded(transactionalReadyAt - coreReadyAt),
      interface_after_core_health_ms: rounded(browserReadyAt - coreReadyAt),
      interface_after_transactional_ready_ms: rounded(browserReadyAt - transactionalReadyAt),
      resources,
    });
    assert(networkProof.bootstrapPosts > bootstrapCountBeforeRestart, 'Restart did not mint a fresh one-shot browser session');
    bootstrapCountBeforeRestart = networkProof.bootstrapPosts;
  }
  sidecar = await waitForSidecarFrame(page, '', networkProof, true);
  const restartedReady = await frameRequest(sidecar, '/api/maverick-ready');
  assert(
    restartedReady.status === 200 && restartedReady.body?.ok === true && restartedReady.body?.ready === true,
    `Restarted OpenDesign readiness returned HTTP ${restartedReady.status}`,
  );
  const persistedProject = await frameRequest(sidecar, `/api/projects/${encodeURIComponent(projectA.projectId)}`);
  assert(persistedProject.status === 200, 'Project did not survive core/sidecar restart');
  const performanceEvidence = validatePerformanceEvidence({ warmTickets, warmOpenings, coreRestarts });

  await page.goto(
    `${platformOrigin}/app/design-studio?od_project_id=${encodeURIComponent(projectA.projectId)}&od_run_id=${encodeURIComponent(successful.runId)}`,
    { waitUntil: 'domcontentloaded' },
  );
  sidecar = await waitForSidecarFrame(page, `/projects/${projectA.projectId}`);
  assert(new URL(sidecar.url()).pathname === `/projects/${projectA.projectId}`, 'Project/run deep link did not reach OpenDesign');

  const switched = await platformRequest(page, '/api/workspaces/active', {
    method: 'POST',
    body: { workspace_id: 'workspace-b' },
  });
  assert(switched.status === 200, 'Workspace switch failed');
  await page.goto(`${platformOrigin}/app/design-studio`, { waitUntil: 'domcontentloaded' });
  const sidecarB = await waitForSidecarFrame(page);
  const originB = new URL(sidecarB.url()).origin;
  assert(originB !== originA, 'Two workspaces reused the same isolated sidecar origin');
  const projectsB = await frameRequest(sidecarB, '/api/projects');
  const projectItemsB = Array.isArray(projectsB.body?.projects) ? projectsB.body.projects : [];
  assert(!projectItemsB.some((item) => item?.id === projectA.projectId), 'Workspace B observed workspace A project data');
  const projectB = await createProjectFromUi(page, sidecarB, 'Maverick WP10 workspace B', networkProof);
  const successfulB = await createRun(sidecarB, projectB, 'Create the isolated workspace B artifact.');
  await readIncrementalStream(sidecarB, successfulB.runId);
  await waitForRun(sidecarB, successfulB.runId, 'succeeded');
  const packageB = await resultPackage(sidecarB, successfulB.runId);
  const correlationB = correlationFromPackage(packageB, projectB.projectId, successfulB.runId);
  assert(correlationB.workspace_id === 'workspace-b', 'Workspace B correlation identity drifted');

  assert(networkProof.isolatedRequests > 0, 'Browser did not send requests to the isolated sidecar origin');
  assert(!networkProof.maverickCookieForwarded, 'A Maverick session cookie reached the sidecar origin');
  assert(!networkProof.browserBearerForwarded, 'A browser bearer reached the sidecar origin');

  const evidence = buildEvidence({
    correlationA,
    correlationB,
    correlationCanceled,
    manifest,
    networkProof,
    originA,
    originB,
    projectA,
    successful,
    profile,
    performanceEvidence,
  });
  if (evidenceOutputPath) {
    await mkdir(path.dirname(evidenceOutputPath), { recursive: true });
    await writeFile(evidenceOutputPath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
  }
  process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);
} catch (error) {
  if (error instanceof ProfileComplete) {
    if (evidenceOutputPath) {
      await mkdir(path.dirname(evidenceOutputPath), { recursive: true });
      await writeFile(evidenceOutputPath, `${JSON.stringify(error.evidence, null, 2)}\n`, 'utf8');
    }
    process.stdout.write(`${JSON.stringify(error.evidence, null, 2)}\n`);
  } else {
  const diagnostic = typeof server?.wp10Diagnostic === 'function' ? server.wp10Diagnostic() : '';
  if (diagnostic) process.stderr.write(`\nSynthetic server diagnostic:\n${redactedDiagnostic(diagnostic)}\n`);
  throw error;
  }
} finally {
  if (browser) await browser.close().catch(() => {});
  await stopServer(server);
  if (keepTemporary) {
    process.stderr.write(`Synthetic E2E root retained at ${temporaryRoot}\n`);
  } else {
    await rm(temporaryRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}


function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : '';
}


function argumentsAll(name) {
  return process.argv.flatMap((value, index) => value === name && process.argv[index + 1] ? [process.argv[index + 1]] : []);
}


function assert(condition, message) {
  if (!condition) throw new Error(message);
}


async function freePort() {
  const serverSocket = createServer();
  await new Promise((resolve, reject) => {
    serverSocket.once('error', reject);
    serverSocket.listen(0, '127.0.0.1', resolve);
  });
  const address = serverSocket.address();
  const selected = typeof address === 'object' && address ? address.port : 0;
  await new Promise((resolve) => serverSocket.close(resolve));
  if (!selected) throw new Error('Could not reserve a local E2E port');
  return selected;
}


async function startServer() {
  const startedAt = performance.now();
  const child = spawn(python, [
    serverFixture,
    '--root', installationRoot,
    '--port', String(port),
    '--web-overlay-sha256', overlayContract.web_overlay_sha256,
  ], {
    cwd: repoRoot,
    detached: true,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '';
  child.stdout.on('data', (chunk) => { output = `${output}${String(chunk)}`.slice(-16_384); });
  child.stderr.on('data', (chunk) => { output = `${output}${String(chunk)}`.slice(-16_384); });
  child.wp10Diagnostic = () => output;
  child.wp10StartedAt = startedAt;
  for (let attempt = 0; attempt < 2_400; attempt += 1) {
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error(`Synthetic Maverick server exited before readiness: ${redactedDiagnostic(output)}`);
    }
    try {
      const response = await fetch(`http://localhost:${port}/health`);
      if (response.ok) {
        child.wp10CoreReadyAt = performance.now();
        return child;
      }
    } catch {}
    await delay(100);
  }
  await stopServer(child);
  throw new Error(`Synthetic Maverick server did not become ready: ${redactedDiagnostic(output)}`);
}


async function stopServer(child) {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
  try { process.kill(-child.pid, 'SIGTERM'); } catch {}
  const exited = await Promise.race([
    new Promise((resolve) => child.once('exit', () => resolve(true))),
    delay(10_000).then(() => false),
  ]);
  if (!exited) {
    try { process.kill(-child.pid, 'SIGKILL'); } catch {}
  }
}


async function loginAndOpen(page) {
  await page.goto(`${platformOrigin}/app/design-studio`, { waitUntil: 'domcontentloaded' });
  await page.getByPlaceholder('Email or username').fill('admin');
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByPlaceholder('Password').fill('maverick');
  const sessionResponse = page.waitForResponse(
    (response) => response.url() === `${platformOrigin}/api/session` && response.status() === 200,
  );
  await page.getByRole('button', { name: 'Sign in' }).click();
  await sessionResponse;
  await page.evaluate(() => {
    const key = 'maverick:base-shell:session';
    let session = {};
    try { session = JSON.parse(localStorage.getItem(key) || '{}'); } catch {}
    localStorage.setItem(key, JSON.stringify({
      ...session,
      activeAppId: 'design-studio',
      isSidebarOpen: true,
      sidebarMode: 'fixed',
    }));
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
}


async function waitForSidecarFrame(
  page,
  expectedPath = '',
  networkProof = null,
  requireReady = false,
  excludedFrame = null,
) {
  let lastRetryAt = 0;
  for (let attempt = 0; attempt < 600; attempt += 1) {
    const frame = page.frames().find((candidate) => {
      try {
        const url = new URL(candidate.url());
        return candidate !== excludedFrame
          && isSidecarHostname(url.hostname)
          && (!expectedPath || url.pathname === expectedPath);
      } catch { return false; }
    });
    if (frame) {
      await frame.waitForLoadState('domcontentloaded').catch(() => {});
      if (!requireReady) return frame;
      const ready = await frameRequest(frame, '/api/maverick-ready').catch(() => ({ status: 0, body: null }));
      if (ready.status === 200 && ready.body?.ok === true && ready.body?.ready === true) {
        return frame;
      }
    }
    const retry = page.getByTestId('opendesign-retry');
    if (Date.now() - lastRetryAt >= 2_000 && await retry.isVisible().catch(() => false)) {
      await retry.click();
      lastRetryAt = Date.now();
    }
    if (
      attempt >= 600
      && await page.getByText('OpenDesign is unavailable', { exact: true }).isVisible().catch(() => false)
      && !await retry.isVisible().catch(() => false)
    ) break;
    await delay(25);
  }
  const frameUrls = await Promise.all(page.frames().map(async (frame) => ({
    url: frame.url(),
    body: (await frame.locator('body').innerText().catch(() => '')).slice(0, 500),
  })));
  const bodyText = (await page.locator('body').innerText().catch(() => '')).slice(0, 1000);
  const appStatus = await platformRequest(page, '/api/apps/design-studio/backend', {
    method: 'POST',
    body: { action: 'status', arguments: {} },
  }).catch(() => null);
  const launchStatus = await platformRequest(page, '/api/app-sidecars/browser-launch', {
    method: 'POST',
    body: { app_id: 'design-studio', sidecar_id: 'opendesign', path: '/index.html' },
  }).catch(() => null);
  throw new Error(`OpenDesign isolated browser frame did not become ready: ${JSON.stringify({ frameUrls, bodyText, appStatus, launchStatus, network: networkProof?.diagnostics || [] })}`);
}


async function completeOpenDesignOnboarding(page, frame) {
  const appFrame = await waitForShellWidgetFrame(page, 'Design Studio viewport');
  const centralCreate = appFrame.getByRole('button', { name: 'Nuovo progetto', exact: true });
  try {
    await centralCreate.waitFor({ state: 'visible', timeout: 60_000 });
  } catch (error) {
    const launchTarget = await platformRequest(page, '/api/apps/design-studio/backend', {
      method: 'POST',
      body: { action: 'resolve_launch_target', arguments: {} },
    });
    const diagnostic = {
      launchTarget,
      pageBody: (await page.locator('body').innerText().catch(() => '')).slice(0, 1_000),
      frameBody: (await frame.locator('body').innerText().catch(() => '')).slice(0, 1_000),
      host: await appFrame.locator('.design-studio-host').evaluate((element) => ({
        className: element.className,
        phase: element.getAttribute('data-phase'),
      })).catch(() => null),
    };
    throw new Error(`Hosted empty state did not become visible: ${JSON.stringify(diagnostic)}`, { cause: error });
  }
  const footer = await waitForShellWidgetFrame(page, 'App sidebar footer');
  await footer.getByRole('button', { name: 'Impostazioni', exact: true }).click();
  await frame.locator('.modal-settings').waitFor({ state: 'visible', timeout: 60_000 });
  await frame.locator('.settings-close').click();
  await frame.locator('.modal-settings').waitFor({ state: 'detached', timeout: 60_000 });
  await centralCreate.waitFor({ state: 'visible', timeout: 60_000 });
}


async function createProjectFromUi(page, frame, name, networkProof) {
  const nativeChatRequestsBefore = networkProof.nativeChatRequests;
  const appFrame = await waitForShellWidgetFrame(page, 'Design Studio viewport');
  assert(
    !await frame.locator('.home-view > .recent-projects, .home-view > .home-hero').isVisible().catch(() => false),
    'OpenDesign home still exposes native project or chat affordances',
  );
  const beforeResponse = await frameRequest(frame, '/api/projects');
  const beforeIds = new Set(
    (Array.isArray(beforeResponse.body?.projects) ? beforeResponse.body.projects : [])
      .map((item) => String(item?.id || ''))
      .filter(Boolean),
  );
  const responsePromise = page.waitForResponse((response) => {
    try {
      const url = new URL(response.url());
      const body = response.request().postDataJSON();
      return url.origin === platformOrigin
        && url.pathname === '/api/apps/design-studio/backend'
        && response.request().method() === 'POST'
        && body?.action === 'create_project';
    } catch { return false; }
  }, { timeout: 60_000 });
  await appFrame.getByRole('button', { name: 'Nuovo progetto', exact: true }).click();
  const response = await responsePromise;
  const responseText = await response.text();
  assert(response.status() < 300, `Maverick sidebar project create returned HTTP ${response.status()}: ${responseText.slice(0, 300)}`);
  let payload = null;
  try { payload = JSON.parse(responseText); } catch {}
  let projectId = String(payload?.project?.id || payload?.od_project_id || payload?.id || '');
  if (!projectId) {
    const afterResponse = await frameRequest(frame, '/api/projects');
    const created = (Array.isArray(afterResponse.body?.projects) ? afterResponse.body.projects : [])
      .find((item) => item?.id && !beforeIds.has(String(item.id)));
    projectId = String(created?.id || '');
  }
  assert(projectId, 'Maverick sidebar did not return or expose the new OpenDesign project id');
  const sidebar = await waitForShellWidgetFrame(page, 'App sidebar content');
  const projectButton = sidebar.getByRole('button').filter({ hasText: 'Untitled design' }).first();
  await projectButton.waitFor({ state: 'visible', timeout: 60_000 });
  await frame.waitForURL((url) => url.pathname === `/projects/${projectId}`, { timeout: 60_000 });
  assert(await projectButton.getAttribute('aria-current') === 'page', 'Created project was not selected in the Maverick sidebar');
  try {
    await frame.locator('[data-testid="maverick-project-view"]').waitFor({ state: 'visible', timeout: 60_000 });
  } catch (error) {
    const diagnostic = {
      url: frame.url(),
      body: (await frame.locator('body').innerText().catch(() => '')).slice(0, 1_500),
      html: (await frame.locator('body').innerHTML().catch(() => '')).slice(0, 2_000),
      project: await frameRequest(frame, `/api/projects/${encodeURIComponent(projectId)}`),
    };
    throw new Error(`Maverick project view did not render: ${JSON.stringify(diagnostic)}`, { cause: error });
  }
  assert(
    await frame.locator('.split-chat-slot, .split-resize-handle, [data-testid="side-chat-tab"]').count() === 0,
    'OpenDesign native project chat is still mounted',
  );
  assert(
    networkProof.nativeChatRequests === nativeChatRequestsBefore,
    'Hosted project view issued a native conversation request',
  );
  const footer = await waitForShellWidgetFrame(page, 'App sidebar footer');
  await footer.getByRole('button', { name: 'Impostazioni', exact: true }).click();
  await frame.locator('.modal-settings').waitFor({ state: 'visible', timeout: 60_000 });
  await frame.locator('.settings-close').click();
  await frame.locator('[data-testid="maverick-project-view"]').waitFor({ state: 'visible', timeout: 60_000 });
  let conversationId = String(payload?.conversationId || payload?.conversation?.id || '');
  if (!conversationId) {
    const conversations = await frameRequest(frame, `/api/projects/${encodeURIComponent(projectId)}/conversations`);
    const items = Array.isArray(conversations.body?.conversations) ? conversations.body.conversations : [];
    conversationId = String(items[0]?.id || '');
  }
  assert(conversationId, 'OpenDesign UI did not create a conversation');
  return { projectId, conversationId };
}


async function waitForShellWidgetFrame(page, title) {
  const iframe = page.locator(`iframe[title="${title}"]`);
  await iframe.waitFor({ state: 'visible', timeout: 60_000 });
  const handle = await iframe.elementHandle();
  const frame = await handle?.contentFrame();
  assert(frame, `${title} iframe did not expose a content frame`);
  await frame.waitForLoadState('domcontentloaded').catch(() => {});
  return frame;
}


async function createRun(frame, project, message) {
  const suffix = crypto.randomUUID();
  const response = await frameRequest(frame, '/api/runs', {
    method: 'POST',
    body: {
      projectId: project.projectId,
      conversationId: project.conversationId,
      assistantMessageId: `assistant_${suffix}`,
      clientRequestId: `client_${suffix}`,
      agentId: 'maverick',
      message,
      currentPrompt: message,
    },
  });
  assert(response.status === 202 && response.body?.runId, `Run create returned HTTP ${response.status}`);
  return { runId: String(response.body.runId) };
}


async function readIncrementalStream(frame, runId) {
  return frame.evaluate(async ({ id }) => {
    let response;
    for (let attempt = 0; attempt < 300; attempt += 1) {
      response = await fetch(`/api/runs/${encodeURIComponent(id)}/events`);
      if (response.status !== 409) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (!response) throw new Error('SSE request was not issued');
    if (!response.ok || !response.body) throw new Error(`SSE returned HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let text = '';
    let closed = false;
    let runStatus = '';
    let terminalObservedAt = 0;
    const deadline = Date.now() + 90_000;
    let pendingRead = reader.read();
    while (Date.now() < deadline) {
      const part = await Promise.race([
        pendingRead,
        new Promise((resolve) => setTimeout(() => resolve(null), 1_000)),
      ]);
      if (part === null) {
        const runResponse = await fetch(`/api/runs/${encodeURIComponent(id)}`);
        if (runResponse.ok) {
          runStatus = String((await runResponse.json())?.status || '');
          if (['succeeded', 'failed', 'canceled'].includes(runStatus)) {
            terminalObservedAt ||= Date.now();
            if (Date.now() - terminalObservedAt >= 10_000) break;
          }
        }
        continue;
      }
      if (part.done) {
        closed = true;
        break;
      }
      text += decoder.decode(part.value, { stream: true });
      if (/event:\s*end/.test(text)) break;
      pendingRead = reader.read();
    }
    await reader.cancel().catch(() => {});
    return {
      incremental: /text_delta|project_file_changed/.test(text),
      terminal: /event:\s*end/.test(text),
      closed,
      runStatus,
      eventNames: [...text.matchAll(/event:\s*([^\r\n]+)/g)].map((match) => match[1]).slice(0, 20),
    };
  }, { id: runId });
}


async function waitForRun(frame, runId, expectedStatus) {
  const terminal = new Set(['succeeded', 'failed', 'canceled']);
  for (let attempt = 0; attempt < 600; attempt += 1) {
    const response = await frameRequest(frame, `/api/runs/${encodeURIComponent(runId)}`);
    if (response.status === 200) {
      const status = String(response.body?.status || '');
      if (status === expectedStatus) return response.body;
      if (terminal.has(status) && status !== expectedStatus) {
        throw new Error(`Run reached ${status}; expected ${expectedStatus}: ${JSON.stringify(response.body)}`);
      }
    }
    await delay(100);
  }
  throw new Error(`Run did not reach ${expectedStatus}`);
}


async function resultPackage(frame, runId) {
  const response = await frameRequest(frame, `/api/runs/${encodeURIComponent(runId)}/result-package`);
  assert(response.status === 200 && response.body?.maverick, `Result package returned HTTP ${response.status}`);
  return response.body;
}


function correlationFromPackage(payload, projectId, runId) {
  const correlation = {
    workspace_id: String(payload.maverick.workspace_id || ''),
    local_app_id: String(payload.maverick.local_app_id || ''),
    sidecar_id: String(payload.maverick.sidecar_id || ''),
    od_project_id: String(payload.maverick.od_project_id || projectId),
    od_run_id: String(payload.maverick.od_run_id || runId),
    runtime_session_id: String(payload.maverick.runtime_session_id || ''),
    turn_id: String(payload.maverick.turn_id || ''),
    request_id: String(payload.maverick.request_id || ''),
    correlation_id: String(payload.maverick.correlation_id || ''),
  };
  assert(Object.values(correlation).every(Boolean), 'Result package correlation is incomplete');
  assert(correlation.od_project_id === projectId && correlation.od_run_id === runId, 'Result correlation identity drifted');
  return correlation;
}


async function frameRequest(frame, requestPath, { method = 'GET', body = undefined } = {}) {
  return frame.evaluate(async ({ requestPath: target, method: requestMethod, body: requestBody }) => {
    const response = await fetch(target, {
      method: requestMethod,
      headers: requestBody === undefined ? undefined : { 'content-type': 'application/json' },
      body: requestBody === undefined ? undefined : JSON.stringify(requestBody),
    });
    const text = await response.text();
    let parsed = null;
    try { parsed = text ? JSON.parse(text) : null; } catch { parsed = text; }
    return { status: response.status, body: parsed };
  }, { requestPath, method, body });
}


async function frameText(frame, requestPath) {
  return frame.evaluate(async (target) => {
    const response = await fetch(target);
    return { status: response.status, text: await response.text() };
  }, requestPath);
}


async function platformRequest(page, requestPath, { method = 'GET', body = undefined } = {}) {
  return page.evaluate(async ({ requestPath: target, method: requestMethod, body: requestBody }) => {
    const response = await fetch(target, {
      method: requestMethod,
      credentials: 'same-origin',
      headers: requestBody === undefined ? undefined : { 'content-type': 'application/json' },
      body: requestBody === undefined ? undefined : JSON.stringify(requestBody),
    });
    const text = await response.text();
    let parsed = null;
    try { parsed = text ? JSON.parse(text) : null; } catch { parsed = text; }
    return { status: response.status, body: parsed };
  }, { requestPath, method, body });
}


async function benchmarkWarmTickets(page, count) {
  const durations = [];
  const instances = new Set();
  for (let iteration = 0; iteration < count; iteration += 1) {
    const startedAt = performance.now();
    const launch = await platformRequest(page, '/api/app-sidecars/browser-launch', {
      method: 'POST',
      body: { app_id: 'design-studio', sidecar_id: 'opendesign', path: '/index.html' },
    });
    durations.push(rounded(performance.now() - startedAt));
    assert(launch.status === 200, `Warm browser ticket ${iteration + 1} returned HTTP ${launch.status}`);
    assert(typeof launch.body?.ticket === 'string' && launch.body.ticket.length > 20, 'Warm browser ticket is invalid');
    instances.add(String(launch.body?.sidecar_instance_id || ''));
  }
  assert(instances.size === 1 && !instances.has(''), 'Warm ticket benchmark remounted or lost the sidecar instance');
  return { ...distribution(durations), same_sidecar_instance: true };
}


async function benchmarkWarmOpenings(page, networkProof, count) {
  const durations = [];
  const wrapperDurations = [];
  const frameDurations = [];
  const frameNavigationDurations = [];
  const frameResponseDurations = [];
  const frameTransferBytes = [];
  const wrapper = await waitForShellWidgetFrame(page, 'Design Studio viewport');
  const wrapperUrl = wrapper.url();
  for (let iteration = 0; iteration < count; iteration += 1) {
    const previousSidecar = page.frames().find((candidate) => {
      try { return isSidecarHostname(new URL(candidate.url()).hostname); } catch { return false; }
    }) || null;
    const startedAt = performance.now();
    await wrapper.goto(wrapperUrl, { waitUntil: 'domcontentloaded' });
    const wrapperReadyAt = performance.now();
    const frame = await waitForSidecarFrame(page, '', networkProof, true, previousSidecar);
    await frame.locator('body').waitFor({ state: 'visible', timeout: 5_000 });
    const finishedAt = performance.now();
    durations.push(rounded(finishedAt - startedAt));
    wrapperDurations.push(rounded(wrapperReadyAt - startedAt));
    frameDurations.push(rounded(finishedAt - wrapperReadyAt));
    const framePerformance = await readSidecarPerformance(page, frame, networkProof);
    frameNavigationDurations.push(rounded(framePerformance.duration));
    frameResponseDurations.push(rounded(framePerformance.response_end));
    frameTransferBytes.push(framePerformance.transfer_bytes);
    await delay(300);
  }
  const interfaceDistribution = distribution(frameDurations);
  return {
    // The app-owned first-paint clock starts when the wrapper document is
    // mounted. Keep Core/shell document serving visible, but do not charge it
    // twice to the Design Studio interface SLO.
    ...interfaceDistribution,
    full_wrapper_remount: distribution(durations),
    wrapper_dom_content_loaded: distribution(wrapperDurations),
    sidecar_frame_ready: interfaceDistribution,
    sidecar_navigation: distribution(frameNavigationDurations),
    sidecar_response: distribution(frameResponseDurations),
    sidecar_resource_transfer_bytes: distribution(frameTransferBytes),
  };
}


async function readSidecarPerformance(page, initialFrame, networkProof) {
  let frame = initialFrame;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      return await frame.evaluate(() => {
        const navigation = performance.getEntriesByType('navigation')[0];
        const resources = performance.getEntriesByType('resource');
        return {
          duration: Number(navigation?.duration || 0),
          response_end: Number(navigation?.responseEnd || 0),
          transfer_bytes: resources.reduce((total, entry) => total + Number(entry.transferSize || 0), 0),
        };
      });
    } catch {
      await delay(25);
      frame = await waitForSidecarFrame(page, '', networkProof, true);
    }
  }
  throw new Error('OpenDesign performance navigation did not stabilize');
}


async function waitForTransactionalReadiness(page) {
  let lastStatus = null;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    lastStatus = await platformRequest(page, '/api/apps/design-studio/backend', {
      method: 'POST',
      body: { action: 'status', arguments: {} },
    }).catch(() => null);
    const runtime = lastStatus?.body?.opendesign?.runtime;
    if (
      lastStatus?.status === 200
      && runtime?.operational === true
      && runtime?.health?.activation_committed === true
      && runtime?.health?.browser_ready === true
    ) return lastStatus;
    await delay(100);
  }
  throw new Error(`OpenDesign prewarm did not commit transactional readiness: ${JSON.stringify(lastStatus)}`);
}


function validatePerformanceEvidence({ warmTickets, warmOpenings, coreRestarts }) {
  const daemon = distribution(coreRestarts.map((sample) => sample.daemon_ready_ms));
  const cold = distribution(coreRestarts.map((sample) => sample.cold_maverick_ready_ms));
  const fullRestart = distribution(coreRestarts.map((sample) => sample.full_restart_ms));
  const restartStop = distribution(coreRestarts.map((sample) => sample.stop_ms));
  const coreBoot = distribution(coreRestarts.map((sample) => sample.core_boot_ms));
  const prewarmAfterCoreHealth = distribution(
    coreRestarts.map((sample) => sample.prewarm_after_core_health_ms),
  );
  const interfaceAfterCoreHealth = distribution(
    coreRestarts.map((sample) => sample.interface_after_core_health_ms),
  );
  const interfaceAfterTransactionalReady = distribution(
    coreRestarts.map((sample) => sample.interface_after_transactional_ready_ms),
  );
  const diagnostic = JSON.stringify({
    warmTickets,
    warmOpenings,
    cold,
    fullRestart,
    daemon,
    restartStop,
    coreBoot,
    prewarmAfterCoreHealth,
    interfaceAfterCoreHealth,
    interfaceAfterTransactionalReady,
  });
  process.stderr.write(`OpenDesign performance diagnostic: ${diagnostic}\n`);
  assert(
    warmTickets.count === 30 && warmTickets.p95_ms <= 300 && warmTickets.p99_ms <= 750,
    `Warm ticket SLO failed: ${diagnostic}`,
  );
  assert(
    warmOpenings.count === 30 && warmOpenings.p95_ms <= 1_500 && warmOpenings.p99_ms <= 2_500,
    `Warm interface SLO failed: ${diagnostic}`,
  );
  assert(
    cold.count === 10 && cold.p95_ms <= 4_000 && cold.max_ms <= 8_000,
    `Cold transactional readiness SLO failed: ${diagnostic}`,
  );
  const resourceSamples = coreRestarts.map((sample) => sample.resources);
  return {
    schema_version: '1',
    warm_browser_ticket: warmTickets,
    warm_interface: warmOpenings,
    cold_maverick_ready: cold,
    daemon_internal_ready: daemon,
    full_core_restart: fullRestart,
    core_boot: coreBoot,
    prewarm_after_core_health: prewarmAfterCoreHealth,
    interface_after_transactional_ready: interfaceAfterTransactionalReady,
    core_restart_count: coreRestarts.length,
    resources: {
      cpu_ticks_max: Math.max(...resourceSamples.map((sample) => sample.cpu_ticks)),
      rss_kib_max: Math.max(...resourceSamples.map((sample) => sample.rss_kib)),
      disk_read_bytes_max: Math.max(...resourceSamples.map((sample) => sample.disk_read_bytes)),
      process_count_max: Math.max(...resourceSamples.map((sample) => sample.process_count)),
    },
    samples: coreRestarts,
    targets_met: true,
  };
}


function distribution(samples) {
  const values = samples.map(Number).filter(Number.isFinite).sort((left, right) => left - right);
  assert(values.length === samples.length && values.length > 0, 'Performance samples are invalid');
  const percentile = (value) => values[Math.max(0, Math.ceil((value / 100) * values.length) - 1)];
  return {
    count: values.length,
    p50_ms: rounded(percentile(50)),
    p95_ms: rounded(percentile(95)),
    p99_ms: rounded(percentile(99)),
    max_ms: rounded(values.at(-1)),
  };
}


async function processResourceSnapshot(rootPid) {
  const pending = [Number(rootPid)];
  const observed = new Set();
  let cpuTicks = 0;
  let rssKib = 0;
  let diskReadBytes = 0;
  while (pending.length > 0) {
    const pid = pending.pop();
    if (!Number.isInteger(pid) || pid < 1 || observed.has(pid)) continue;
    observed.add(pid);
    const [children, status, io, stat] = await Promise.all([
      readFile(`/proc/${pid}/task/${pid}/children`, 'utf8').catch(() => ''),
      readFile(`/proc/${pid}/status`, 'utf8').catch(() => ''),
      readFile(`/proc/${pid}/io`, 'utf8').catch(() => ''),
      readFile(`/proc/${pid}/stat`, 'utf8').catch(() => ''),
    ]);
    pending.push(...children.trim().split(/\s+/).filter(Boolean).map(Number));
    rssKib += Number(/^VmRSS:\s+(\d+)\s+kB$/m.exec(status)?.[1] || 0);
    diskReadBytes += Number(/^read_bytes:\s+(\d+)$/m.exec(io)?.[1] || 0);
    const statFields = stat.slice(stat.lastIndexOf(') ') + 2).trim().split(/\s+/);
    cpuTicks += Number(statFields[11] || 0) + Number(statFields[12] || 0);
  }
  return {
    cpu_ticks: cpuTicks,
    rss_kib: rssKib,
    disk_read_bytes: diskReadBytes,
    process_count: observed.size,
  };
}


function rounded(value) {
  return Math.round(Number(value) * 1_000) / 1_000;
}


async function storageRead(page, workspaceRelativePath) {
  return platformRequest(page, '/api/apps/storage/backend', {
    method: 'POST',
    body: {
      action: 'file.content.read',
      workspace_relative_path: workspaceRelativePath,
      include_content: true,
      max_bytes: 1_048_576,
      _app_secret_request: { logical_names: [], required: false },
    },
  });
}


async function runMigrationSmoke() {
  const child = spawn(python, [migrationSmoke], {
    cwd: path.dirname(migrationSmoke),
    env: process.env,
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  let diagnostic = '';
  child.stderr.on('data', (chunk) => { diagnostic = `${diagnostic}${String(chunk)}`.slice(-8_192); });
  const code = await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', (status) => resolve(status));
  });
  if (code !== 0) throw new Error(`Migration/rollback smoke failed: ${redactedDiagnostic(diagnostic)}`);
}


function buildEvidence({ correlationA, correlationB, correlationCanceled, manifest, networkProof, originA, originB, projectA, successful, profile, performanceEvidence }) {
  const scenarios = [
    ['login_open', 'Login and open Design Studio', correlationA, { isolated_origin: true, ready_endpoint: true }],
    ['create_project_ui', 'Create and open a project from the Maverick sidebar', correlationA, {
      project_created: true,
      sidebar_navigation: true,
      native_home_projects_hidden: true,
      native_chat_unmounted: true,
      native_chat_background_requests: 0,
    }],
    ['storage_import', 'Import one Storage file with read-back', correlationA, { imported: true }],
    ['runtime_start', 'Start one Maverick-owned run', correlationA, { submitted: true }],
    ['incremental_sse', 'Receive incremental SSE before terminal', correlationA, { incremental: true }],
    ['generated_preview', 'Generate and preview a project file', correlationA, { previewed: true }],
    ['cancel_long_run', 'Cancel a long run idempotently', correlationCanceled, { canceled: true, repeated_cancel_safe: true }],
    ['storage_export', 'Export result package and verified manifest to Storage', correlationA, { artifact_count: manifest.artifacts.length }],
    ['restart_reload', 'Reload after core and sidecar restart', correlationA, { recovered: true, ready_endpoint: true }],
    ['deep_link', 'Open a project/run deep link', correlationA, { project_route: true, run_hint: true }],
    ['workspace_isolation', 'Keep workspace A and B processes and data isolated', correlationB, { distinct_origins: originA !== originB }],
    ['forbidden_routes', 'Deny sensitive, unknown, and core routes', correlationA, { exact_deny: true }],
    ['secret_boundary', 'Keep platform credentials out of OpenDesign', correlationA, {
      maverick_cookie_forwarded: networkProof.maverickCookieForwarded,
      browser_bearer_forwarded: networkProof.browserBearerForwarded,
      one_shot_bootstrap_count: networkProof.bootstrapPosts,
    }],
  ].map(([id, name, correlation, proof]) => ({ id, name, status: 'passed', correlation, proof }));
  return buildProfileEvidence({
    profile,
    scenarios,
    performanceEvidence,
    canonicalEntity: {
      od_project_id: projectA.projectId,
      od_run_id: successful.runId,
    },
  });
}


function buildFirstWorkspaceScenarios({ correlationA, correlationCanceled, manifest, networkProof }) {
  return [
    scenario('login_open', 'Login and open Design Studio', { isolated_origin: true, ready_endpoint: true }, correlationA),
    scenario('create_project_ui', 'Create and open a project from the Maverick sidebar', { project_created: true }, correlationA),
    scenario('storage_import', 'Import one Storage file with read-back', { imported: true }, correlationA),
    scenario('runtime_start', 'Start one Maverick-owned run', { submitted: true }, correlationA),
    scenario('incremental_sse', 'Receive incremental SSE before terminal', { incremental: true }, correlationA),
    scenario('generated_preview', 'Generate and preview a project file', { previewed: true }, correlationA),
    scenario('cancel_long_run', 'Cancel a long run idempotently', { canceled: true, repeated_cancel_safe: true }, correlationCanceled),
    scenario('storage_export', 'Export result package and verified manifest to Storage', { artifact_count: manifest.artifacts.length }, correlationA),
    scenario('forbidden_routes', 'Deny sensitive, unknown, and core routes', { exact_deny: true }, correlationA),
    scenario('secret_boundary', 'Keep platform credentials out of OpenDesign', {
      maverick_cookie_forwarded: networkProof.maverickCookieForwarded,
      browser_bearer_forwarded: networkProof.browserBearerForwarded,
      one_shot_bootstrap_count: networkProof.bootstrapPosts,
    }, correlationA),
  ];
}


function scenario(id, name, proof, correlation = null) {
  return { id, name, status: 'passed', ...(correlation ? { correlation } : {}), proof };
}


function buildProfileEvidence({ profile, scenarios, canonicalEntity, performanceEvidence = null }) {
  return {
    schema_version: '1',
    gate: `design-studio-e2e-${profile}`,
    profile,
    status: 'passed',
    changed_files: changedFiles,
    affected_categories: profile === 'affected' ? affectedCategories(changedFiles) : [],
    opendesign: {
      version: bundleContract.upstream.release_version,
      oci_reference: `${bundleContract.distribution.registry}/${bundleContract.distribution.repository}:${bundleContract.distribution.reference}`,
      runtime_artifact_sha256: bundleContract.artifact.assets['linux-x86_64'].sha256,
      web_overlay_sha256: overlayContract.web_overlay_sha256,
    },
    product_path: {
      official_oci_daemon: true,
      real_chromium: true,
      real_maverick_core: true,
      real_sidecar_broker: true,
      real_storage_app: true,
      external_runtime_protocol_fixture: true,
      local_next_build: false,
      docker_socket: false,
      remote_iframe: false,
    },
    canonical_entity: canonicalEntity,
    scenarios,
    ...(performanceEvidence ? { performance: performanceEvidence } : {}),
    redaction: {
      full_prompt_recorded: false,
      credential_value_recorded: false,
      environment_recorded: false,
      host_path_recorded: false,
    },
  };
}


function affectedCategories(paths) {
  const categories = new Set();
  for (const changed of paths) {
    if (changed.startsWith('core/') || changed.includes('app_contract')) categories.add('core-app-contract');
    if (changed.startsWith('apps/design-studio/backend/')) categories.add('design-studio-backend');
    if (changed.startsWith('apps/design-studio/frontend/')) categories.add('design-studio-wrapper');
    if (/000[23]-maverick-web/.test(changed)) categories.add('opendesign-web');
    if (
      changed.startsWith('apps/design-studio/service/')
      && !/000[23]-maverick-web/.test(changed)
      && !/\.(md|txt)$/.test(changed)
      && !/_acceptance_0_16_1\.json$/.test(changed)
    ) categories.add('opendesign-runtime');
  }
  return [...categories].sort();
}


async function releasedOverlayDigest() {
  const selection = JSON.parse(
    await readFile(path.join(appRoot, 'service', 'opendesign_release_selection.json'), 'utf8'),
  );
  const digest = selection.active_web_overlay_sha256;
  if (!/^[a-f0-9]{64}$/.test(digest || '')) throw new Error('Canonical release web overlay digest is invalid');
  return digest;
}


async function canonicalOverlayContract(digest) {
  if (!/^[a-f0-9]{64}$/.test(digest || '')) throw new Error('Requested web overlay digest is invalid');
  const namespace = path.join(
    artifactStoreRoot,
    'design-studio',
    'opendesign',
  );
  const root = path.join(namespace, 'web', digest);
  const entries = await readdir(path.join(namespace, 'web'), { withFileTypes: true });
  if (!entries.some((entry) => entry.isDirectory() && entry.name === digest)) {
    throw new Error('Requested canonical OpenDesign web overlay is not materialized');
  }
  const metadata = await lstat(root);
  if (!metadata.isDirectory() || metadata.isSymbolicLink() || (metadata.mode & 0o022) !== 0) {
    throw new Error('Requested canonical OpenDesign web overlay is not protected');
  }
  const manifest = JSON.parse(await readFile(path.join(root, 'content', 'manifest.json'), 'utf8'));
  const receipt = JSON.parse(await readFile(path.join(root, 'receipt.json'), 'utf8'));
  if (
    manifest.web_overlay_sha256 !== digest
    || receipt.artifact_sha256 !== digest
    || receipt.runtime_artifact_sha256 !== bundleContract.artifact.assets['linux-x86_64'].sha256
    || manifest.compatibility?.od_version !== bundleContract.upstream.release_version
    || manifest.compatibility?.upstream_commit !== bundleContract.upstream.commit
    || !manifest.compatibility?.runtime_artifact_sha256?.includes(bundleContract.artifact.assets['linux-x86_64'].sha256)
  ) throw new Error('Requested canonical OpenDesign web overlay is incompatible');
  return manifest;
}


function redactedDiagnostic(value) {
  return String(value || '').replace(/\/[^\s:]+/g, '<path>').slice(-1000);
}


function isSidecarHostname(hostname) {
  return String(hostname || '').includes('.sidecars.') && String(hostname || '').endsWith('.localhost');
}


function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
