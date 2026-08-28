#!/usr/bin/env node

/** Verify the deployed Design Studio through its real public HTTPS origin. */

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';


const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..', '..', '..');
const platformOrigin = requiredOrigin(argument('--platform-origin'));
const authSessionsFile = requiredArgument('--auth-sessions-file');
const projectId = argument('--project-id');
const storageInputPath = argument('--storage-input-path');
const evidenceOutput = argument('--evidence-output');
const platformHostname = new URL(platformOrigin).hostname;
const sidecarSuffix = `.sidecars.${platformHostname}`;
process.env.PLAYWRIGHT_BROWSERS_PATH ||= process.env.MAVERICK_PLAYWRIGHT_BROWSERS_PATH
  || path.resolve(repoRoot, '..', '..', '.cache', 'ms-playwright');
const { chromium } = await import('playwright');

let browser;
let cleanupFrame = null;
let cleanupProjectId = '';
try {
  const sessionId = await newestActiveSession(authSessionsFile);
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await context.addCookies([{
    name: 'maverick_session',
    value: sessionId,
    domain: platformHostname,
    path: '/',
    httpOnly: true,
    secure: true,
    sameSite: 'Lax',
  }]);
  const page = await context.newPage();
  const proof = {
    bootstrapPosts: 0,
    failedSidecarRequests: [],
    maverickCookieForwarded: false,
    readyHeaders: {},
  };
  page.on('request', (request) => {
    if (!isSidecarUrl(request.url())) return;
    if (request.headers().cookie?.includes('maverick_session=')) proof.maverickCookieForwarded = true;
    const url = new URL(request.url());
    if (request.method() === 'POST' && url.pathname === '/.well-known/maverick-sidecar-bootstrap') {
      proof.bootstrapPosts += 1;
    }
  });
  page.on('response', (response) => {
    if (!isSidecarUrl(response.url())) return;
    const url = new URL(response.url());
    if (url.pathname === '/api/maverick-ready' && response.status() === 200) {
      proof.readyHeaders = response.headers();
    }
  });
  page.on('requestfailed', (request) => {
    if (!isSidecarUrl(request.url())) return;
    proof.failedSidecarRequests.push({
      path: new URL(request.url()).pathname,
      error: String(request.failure()?.errorText || 'request_failed').slice(0, 120),
    });
  });

  const session = await context.request.get(`${platformOrigin}/api/session`);
  assert(session.status() === 200 && (await session.json()).authenticated === true, 'Hosted auth session is not active');

  await page.goto(`${platformOrigin}/app/design-studio`, { waitUntil: 'domcontentloaded' });
  let frame = await waitForSidecarFrame(page);
  const origin = new URL(frame.url()).origin;
  const ready = await frameRequest(frame, '/api/maverick-ready');
  assert(ready.status === 200 && ready.body?.ok === true && ready.body?.ready === true, `Hosted readiness returned HTTP ${ready.status}`);
  const projects = await frameRequest(frame, '/api/projects');
  assert(projects.status === 200, `Hosted project listing returned HTTP ${projects.status}`);
  await verifyNativeSettings(page, frame, projectCount(projects.body) === 0);
  if (projectId) {
    const persisted = await frameRequest(frame, `/api/projects/${encodeURIComponent(projectId)}`);
    assert(persisted.status === 200, `Persisted project lookup returned HTTP ${persisted.status}`);
  }
  assert(proof.bootstrapPosts >= 1, 'The hosted browser did not use the one-shot bootstrap POST');
  assert(!proof.maverickCookieForwarded, 'The Maverick platform cookie reached the sidecar origin');
  assert(proof.failedSidecarRequests.length === 0, `Hosted sidecar requests failed: ${JSON.stringify(proof.failedSidecarRequests)}`);
  assert(!('x-frame-options' in proof.readyHeaders), 'The hosted sidecar response still exposes X-Frame-Options');
  assert(
    String(proof.readyHeaders['content-security-policy'] || '').includes(`frame-ancestors ${platformOrigin}`),
    'The hosted sidecar frame-ancestors policy does not name the platform origin',
  );
  const sidecarCookie = (await context.cookies(origin)).find((cookie) => cookie.name !== 'maverick_session');
  assert(sidecarCookie?.httpOnly === true, 'The sidecar bootstrap cookie is not HttpOnly');
  assert(sidecarCookie?.secure === true, 'The sidecar bootstrap cookie is not Secure');
  assert(sidecarCookie?.sameSite === 'Strict', 'The sidecar bootstrap cookie is not SameSite=Strict');
  assert(sidecarCookie?.domain === new URL(origin).hostname, 'The sidecar bootstrap cookie escaped its exact host');

  const bootstrapBeforeReload = proof.bootstrapPosts;
  await page.reload({ waitUntil: 'domcontentloaded' });
  frame = await waitForSidecarFrame(page);
  const reloaded = await frameRequest(frame, '/api/maverick-ready');
  assert(reloaded.status === 200 && proof.bootstrapPosts > bootstrapBeforeReload, 'Hosted reload did not mint a fresh ready session');

  if (projectId) {
    await page.goto(
      `${platformOrigin}/app/design-studio?od_project_id=${encodeURIComponent(projectId)}`,
      { waitUntil: 'domcontentloaded' },
    );
    frame = await waitForSidecarFrame(page, `/projects/${projectId}`);
    assert(new URL(frame.url()).pathname === `/projects/${projectId}`, 'Hosted project deep link did not reach OpenDesign');
  }

  let writeFlow = null;
  if (storageInputPath) {
    await page.goto(`${platformOrigin}/app/design-studio`, { waitUntil: 'domcontentloaded' });
    frame = await waitForSidecarFrame(page);
    const project = await createProjectFromUi(page, frame, `Hosted acceptance ${new Date().toISOString()}`);
    cleanupFrame = frame;
    cleanupProjectId = project.projectId;
    const imported = await frameRequest(frame, '/api/import/storage', {
      method: 'POST',
      body: { project_id: project.projectId, workspace_relative_path: storageInputPath },
    });
    assert(imported.status === 200, `Hosted Storage import returned HTTP ${imported.status}`);
    const importedName = storageInputPath.split('/').at(-1);
    const importedRead = await frameText(frame, `/api/projects/${encodeURIComponent(project.projectId)}/raw/${encodeURIComponent(importedName)}`);
    assert(importedRead.status === 200 && importedRead.text.includes('governed Storage import boundary'), 'Hosted Storage import read-back failed');

    const run = await createRun(frame, project, 'Create index.html containing the exact text Hosted Design Studio acceptance.');
    const streamPromise = readIncrementalStream(frame, run.runId);
    const completed = await waitForRun(frame, run.runId, 'succeeded');
    const stream = await streamPromise;
    assert(stream.incremental && stream.terminal, `Hosted SSE proof is incomplete: ${JSON.stringify(stream)}`);
    const result = await frameRequest(frame, `/api/runs/${encodeURIComponent(run.runId)}/result-package`);
    assert(result.status === 200 && result.body?.maverick, `Hosted result package returned HTTP ${result.status}`);
    const exported = await frameRequest(frame, '/api/export/storage', {
      method: 'POST',
      body: { project_id: project.projectId, run_id: run.runId },
    });
    assert(exported.status === 200, `Hosted Storage export returned HTTP ${exported.status}`);
    const manifestPath = `storage/generated/design-studio/${project.projectId}/${run.runId}/manifest.json`;
    const manifest = await storageRead(page, manifestPath);
    assert(manifest.status === 200, `Hosted export manifest read returned HTTP ${manifest.status}`);

    const removed = await frameRequest(frame, `/api/projects/${encodeURIComponent(project.projectId)}`, { method: 'DELETE' });
    assert([200, 204].includes(removed.status), `Hosted project deletion returned HTTP ${removed.status}`);
    const deletedLookup = await frameRequest(frame, `/api/projects/${encodeURIComponent(project.projectId)}`);
    assert(deletedLookup.status === 404, `Deleted hosted project remained visible with HTTP ${deletedLookup.status}`);
    cleanupProjectId = '';
    writeFlow = {
      storage_import: true,
      run_succeeded: completed.status === 'succeeded',
      sse_incremental: true,
      result_package: true,
      storage_export: true,
      project_deleted: true,
    };
  }

  const result = {
    schema_version: '1',
    gate: 'hosted-origin',
    status: 'passed',
    ok: true,
    platform_origin: platformOrigin,
    sidecar_origin: origin,
    ready: true,
    project_count: projectCount(projects.body),
    persisted_project: Boolean(projectId),
    reload: true,
    deep_link: Boolean(projectId),
    tls_verified_by_chromium: true,
    bootstrap_cookie_secure: true,
    x_frame_options_absent: true,
    write_flow: writeFlow,
  };
  if (evidenceOutput) await writeEvidence(evidenceOutput, result);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
} finally {
  if (cleanupFrame && cleanupProjectId) {
    await frameRequest(cleanupFrame, `/api/projects/${encodeURIComponent(cleanupProjectId)}`, { method: 'DELETE' }).catch(() => {});
  }
  await browser?.close();
}


async function newestActiveSession(filename) {
  const target = path.isAbsolute(filename) ? filename : path.resolve(repoRoot, filename);
  const payload = JSON.parse(await readFile(target, 'utf8'));
  assert(Array.isArray(payload), 'Auth session store is not an array');
  const now = Date.now();
  const active = payload
    .filter((item) => item?.status === 'active' && storedDate(item?.expires_at) > now && typeof item?.session_id === 'string')
    .sort((left, right) => storedDate(left.last_seen_at || left.created_at) - storedDate(right.last_seen_at || right.created_at));
  assert(active.length > 0, 'No active hosted auth session is available');
  return active.at(-1).session_id;
}


async function writeEvidence(filename, result) {
  const target = path.isAbsolute(filename) ? filename : path.resolve(repoRoot, filename);
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, `${JSON.stringify(result, null, 2)}\n`, { encoding: 'utf8', mode: 0o644 });
}


function storedDate(value) {
  const serialized = value && typeof value === 'object' ? value.__maverick_datetime__ : value;
  return Date.parse(String(serialized || ''));
}


async function waitForSidecarFrame(page, expectedPath = '') {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    const frame = page.frames().find((candidate) => {
      if (!isSidecarUrl(candidate.url())) return false;
      return !expectedPath || new URL(candidate.url()).pathname === expectedPath;
    });
    if (frame) {
      await frame.waitForLoadState('domcontentloaded').catch(() => {});
      return frame;
    }
    const retry = page.getByRole('button', { name: 'Retry securely' });
    if (await retry.isVisible().catch(() => false)) await retry.click();
    await delay(200);
  }
  const diagnostics = await Promise.all(page.frames().map(async (frame) => ({
    url: redactedUrl(frame.url()),
    body: (await frame.locator('body').innerText().catch(() => '')).slice(0, 300),
  })));
  throw new Error(`Hosted OpenDesign frame did not become ready: ${JSON.stringify(diagnostics)}`);
}


async function createProjectFromUi(page, frame, name) {
  const footer = await waitForShellWidgetFrame(page, 'App sidebar footer');
  const responsePromise = page.waitForResponse((response) => {
    try {
      const url = new URL(response.url());
      const body = response.request().postDataJSON();
      return url.origin === platformOrigin
        && url.pathname === '/api/apps/design-studio/backend'
        && response.request().method() === 'POST'
        && body?.action === 'create_project';
    } catch {
      return false;
    }
  }, { timeout: 60_000 });
  await footer.getByRole('button', { name: 'Nuovo progetto', exact: true }).click();
  const response = await responsePromise;
  const body = JSON.parse(await response.text());
  assert(response.status() < 300, `Hosted project creation returned HTTP ${response.status()}`);
  const createdProjectId = String(body?.od_project_id || body?.project?.id || body?.id || '');
  assert(createdProjectId, 'Hosted UI project creation returned no project id');
  await frame.waitForURL((url) => url.pathname === `/projects/${createdProjectId}`, { timeout: 60_000 });
  const workspace = frame.locator('[data-testid="file-workspace"]');
  await workspace.waitFor({ state: 'visible', timeout: 60_000 });
  const workspaceBox = await workspace.boundingBox();
  assert(
    workspaceBox && workspaceBox.height >= 300,
    `Hosted OpenDesign workspace remained compressed: ${JSON.stringify(workspaceBox)}`,
  );
  await frame.getByText('Tutti i file del progetto', { exact: true }).first().waitFor({ state: 'visible', timeout: 60_000 });
  assert(!await frame.getByText('sidecar_route_blocked', { exact: true }).isVisible().catch(() => false), 'Hosted editor handoff called a blocked local route');
  const nativeAssistant = frame.locator('.split-chat-slot');
  assert(await nativeAssistant.count() === 1 && !await nativeAssistant.isVisible(), 'Hosted native assistant was not delegated to Maverick Chat');
  await footer.getByRole('button', { name: 'Strumenti', exact: true }).click();
  const sketchEditor = frame.locator('[data-testid="sketch-excalidraw-editor"]');
  await sketchEditor.waitFor({ state: 'visible', timeout: 60_000 });
  await sketchEditor.locator('[data-testid="toolbar-selection"]').waitFor({ state: 'visible', timeout: 60_000 });
  assert(!await nativeAssistant.isVisible(), 'Strumenti opened the assistant instead of the drawing toolbar');
  let conversationId = String(body?.conversationId || body?.conversation?.id || '');
  if (!conversationId) {
    const conversations = await frameRequest(frame, `/api/projects/${encodeURIComponent(createdProjectId)}/conversations`);
    const items = Array.isArray(conversations.body?.conversations) ? conversations.body.conversations : [];
    conversationId = String(items[0]?.id || '');
  }
  assert(conversationId, 'Hosted UI project creation returned no conversation id');
  return { projectId: createdProjectId, conversationId };
}


async function verifyNativeSettings(page, frame, expectEmpty) {
  const appFrame = await waitForShellWidgetFrame(page, 'Design Studio viewport');
  if (expectEmpty) {
    await appFrame.getByRole('button', { name: 'Nuovo progetto', exact: true }).waitFor({ state: 'visible', timeout: 60_000 });
  }
  const footer = await waitForShellWidgetFrame(page, 'App sidebar footer');
  await footer.getByRole('button', { name: 'Impostazioni', exact: true }).click();
  await frame.locator('.modal-settings').waitFor({ state: 'visible', timeout: 60_000 });
  await frame.locator('.settings-close').click();
  await frame.locator('.modal-settings').waitFor({ state: 'detached', timeout: 60_000 });
  if (expectEmpty) {
    await appFrame.getByRole('button', { name: 'Nuovo progetto', exact: true }).waitFor({ state: 'visible', timeout: 60_000 });
  }
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
  assert(response.status === 202 && response.body?.runId, `Hosted run creation returned HTTP ${response.status}`);
  return { runId: String(response.body.runId) };
}


async function waitForRun(frame, runId, expectedStatus) {
  const deadline = Date.now() + 180_000;
  const terminal = new Set(['succeeded', 'failed', 'canceled']);
  while (Date.now() < deadline) {
    const response = await frameRequest(frame, `/api/runs/${encodeURIComponent(runId)}`);
    if (response.status === 200) {
      const status = String(response.body?.status || '');
      if (status === expectedStatus) return response.body;
      if (terminal.has(status)) throw new Error(`Hosted run reached ${status}; expected ${expectedStatus}`);
    }
    await delay(250);
  }
  throw new Error(`Hosted run did not reach ${expectedStatus}`);
}


async function readIncrementalStream(frame, runId) {
  return frame.evaluate(async (id) => {
    let response;
    for (let attempt = 0; attempt < 300; attempt += 1) {
      response = await fetch(`/api/runs/${encodeURIComponent(id)}/events`);
      if (response.status !== 409) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (!response?.ok || !response.body) throw new Error(`Hosted SSE returned HTTP ${response?.status || 0}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let text = '';
    const deadline = Date.now() + 180_000;
    let pendingRead = reader.read();
    while (Date.now() < deadline) {
      const part = await Promise.race([
        pendingRead,
        new Promise((resolve) => setTimeout(() => resolve(null), 1_000)),
      ]);
      if (part === null) continue;
      if (part.done) break;
      text += decoder.decode(part.value, { stream: true });
      if (/event:\s*end/.test(text)) break;
      pendingRead = reader.read();
    }
    await reader.cancel().catch(() => {});
    return {
      incremental: /text_delta|project_file_changed/.test(text),
      terminal: /event:\s*end/.test(text),
      event_names: [...text.matchAll(/event:\s*([^\r\n]+)/g)].map((match) => match[1]).slice(0, 20),
    };
  }, runId);
}


async function frameRequest(frame, requestPath, { method = 'GET', body = undefined } = {}) {
  return frame.evaluate(async ({ target, requestMethod, requestBody }) => {
    const response = await fetch(target, {
      method: requestMethod,
      headers: requestBody === undefined ? undefined : { 'content-type': 'application/json' },
      body: requestBody === undefined ? undefined : JSON.stringify(requestBody),
    });
    const text = await response.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = text; }
    return { status: response.status, body };
  }, { target: requestPath, requestMethod: method, requestBody: body });
}


async function frameText(frame, requestPath) {
  return frame.evaluate(async (target) => {
    const response = await fetch(target);
    return { status: response.status, text: await response.text() };
  }, requestPath);
}


async function storageRead(page, workspaceRelativePath) {
  return page.evaluate(async (target) => {
    const response = await fetch('/api/apps/storage/backend', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        action: 'file.content.read',
        workspace_relative_path: target,
        include_content: true,
        max_bytes: 1_048_576,
        _app_secret_request: { logical_names: [], required: false },
      }),
    });
    return { status: response.status, body: await response.json().catch(() => null) };
  }, workspaceRelativePath);
}


function isSidecarUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname.endsWith(sidecarSuffix);
  } catch {
    return false;
  }
}


function projectCount(payload) {
  const projects = Array.isArray(payload?.projects) ? payload.projects : Array.isArray(payload) ? payload : [];
  return projects.length;
}


function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? String(process.argv[index + 1] || '').trim() : '';
}


function requiredArgument(name) {
  const value = argument(name);
  assert(value, `${name} is required`);
  return value;
}


function requiredOrigin(value) {
  assert(value, '--platform-origin is required');
  const url = new URL(value);
  assert(url.protocol === 'https:' && url.origin === value, '--platform-origin must be a clean HTTPS origin');
  return url.origin;
}


function redactedUrl(value) {
  try {
    const url = new URL(value);
    return `${url.origin}${url.pathname}`;
  } catch {
    return '';
  }
}


function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}


function assert(condition, message) {
  if (!condition) throw new Error(message);
}
