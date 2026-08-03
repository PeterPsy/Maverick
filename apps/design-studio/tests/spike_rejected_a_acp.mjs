#!/usr/bin/env node

/** Reproduce the real-browser G3 A-ACP spike against a pinned upstream checkout. */

import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';


const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const fixturePath = path.join(scriptDir, 'fixtures', 'rejected_a_acp_shim.py');
const upstreamArgument = argument('--upstream-root');
if (!upstreamArgument) throw new Error('--upstream-root is required');
const upstreamRoot = path.resolve(upstreamArgument);

const daemonCli = path.join(upstreamRoot, 'apps', 'daemon', 'dist', 'cli.js');
const playwrightModule = path.join(
  upstreamRoot,
  'e2e',
  'node_modules',
  '@playwright',
  'test',
  'index.mjs',
);
const tempRoot = await mkdtemp(path.join(os.tmpdir(), 'maverick-g3-a-acp-'));
const tracePath = path.join(tempRoot, 'acp-trace.jsonl');
const configPath = path.join(tempRoot, 'agents.local.json');
const dataRoot = path.join(tempRoot, 'data');
const homeRoot = path.join(tempRoot, 'home');
const port = await freePort();
const baseUrl = `http://127.0.0.1:${port}`;
let daemon = null;
let browser = null;
let daemonOutput = '';

try {
  await mkdir(dataRoot, { recursive: true });
  await mkdir(homeRoot, { recursive: true });
  await writeFile(
    configPath,
    `${JSON.stringify(
      {
        agents: [
          {
            id: 'maverick',
            name: 'Maverick ACP transport spike',
            baseAgent: 'kimi',
            bin: path.basename(fixturePath),
            versionArgs: ['--version'],
            env: { MAVERICK_ACP_SPIKE_TRACE: tracePath },
          },
        ],
      },
      null,
      2,
    )}\n`,
    'utf8',
  );
  const minimalPath = [path.dirname(fixturePath), '/usr/local/bin', '/usr/bin', '/bin'].join(':');
  daemon = spawn(process.execPath, [daemonCli, '--no-open', '--port', String(port)], {
    cwd: upstreamRoot,
    detached: true,
    env: {
      PATH: minimalPath,
      HOME: homeRoot,
      OD_DATA_DIR: dataRoot,
      OD_AGENT_PROFILES_CONFIG: configPath,
      OD_PORT: String(port),
      OD_BIND_HOST: '127.0.0.1',
      OD_ACP_STAGE_TIMEOUT_MS: '1000',
      NEXT_TELEMETRY_DISABLED: '1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  daemon.stdout.on('data', (chunk) => appendDaemonOutput(chunk));
  daemon.stderr.on('data', (chunk) => appendDaemonOutput(chunk));
  await waitForServer(baseUrl);

  const rootResponse = await fetch(`${baseUrl}/`);
  if (!rootResponse.ok) {
    throw new Error(
      'OpenDesign web export is missing; run `pnpm --filter @open-design/web build` in the upstream checkout.',
    );
  }
  await checkedJson(`${baseUrl}/api/app-config`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      agentId: 'maverick',
      telemetry: { metrics: false, content: false, artifactManifest: false },
      privacyDecisionAt: Date.now(),
    }),
  });
  await waitForAgent(baseUrl, 'maverick');

  const { chromium } = await import(pathToFileURL(playwrightModule).href);
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  const browserProof = await runBrowserProof(page);
  const trace = await readTrace(tracePath);

  assert(browserProof.ui.title === 'Open Design', 'production UI did not load');
  assert(browserProof.streaming.createStatus === 202, 'run create did not return 202');
  assert(browserProof.streaming.statusAtFirstSse === 'running', 'SSE marker was not incremental');
  assert(browserProof.streaming.terminalStatus === 'succeeded', 'success run did not succeed');
  assert(browserProof.fileWrite.expectedPresent, 'project file write was not visible');
  assert(browserProof.resume.terminalStatus === 'succeeded', 'follow-up run did not complete');
  assert(browserProof.failure.terminalStatus === 'failed', 'failure package drifted');
  assert(browserProof.timeout.terminalStatus === 'failed', 'timeout package drifted');
  assert(browserProof.cancel.terminalStatus === 'canceled', 'cancel package drifted');
  assert(browserProof.cancel.firstStatus === 200 && browserProof.cancel.secondStatus === 200, 'cancel was not idempotent');

  const sessionNew = trace.filter((entry) => entry.event === 'session_new');
  assert(sessionNew.length > 0, 'ACP peer never received session/new');
  assert(
    sessionNew.every(
      (entry) =>
        entry.open_design_run_id === null
        && JSON.stringify(entry.param_keys) === JSON.stringify(['cwd', 'mcpServers']),
    ),
    'ACP session/new identity shape changed',
  );
  assert(
    trace.every(
      (entry) => !Array.isArray(entry.provider_secret_names) || entry.provider_secret_names.length === 0,
    ),
    'provider secret name reached the ACP peer',
  );
  assert(trace.filter((entry) => entry.event === 'session_cancel').length === 1, 'ACP cancel count drifted');
  assert(trace.filter((entry) => entry.event === 'session_load').length === 0, 'custom profile unexpectedly resumed');

  console.log(
    JSON.stringify(
      {
        gate: 'G3',
        option: 'A-ACP',
        decision: 'rejected',
        ui: { title: browserProof.ui.title, productionExport: true },
        criteria: {
          createRun: true,
          incrementalSse: true,
          projectFile: true,
          idempotentCancel: true,
          timeout: true,
          terminalPackages: browserProof.resultPackages,
          noProviderSecret: true,
          fullCorrelation: false,
          actorAttribution: false,
          resume: false,
          runScopedCapability: false,
        },
      },
      null,
      2,
    ),
  );
} catch (error) {
  if (daemonOutput.trim()) process.stderr.write(`\nDaemon output (redaction-safe local spike):\n${daemonOutput}\n`);
  throw error;
} finally {
  if (browser) await browser.close().catch(() => {});
  await stopProcessGroup(daemon);
  await rm(tempRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
}


function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : null;
}


function assert(condition, message) {
  if (!condition) throw new Error(message);
}


function appendDaemonOutput(chunk) {
  daemonOutput = `${daemonOutput}${String(chunk)}`.slice(-32_768);
}


async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  const selected = typeof address === 'object' && address ? address.port : 0;
  await new Promise((resolve) => server.close(resolve));
  if (!selected) throw new Error('failed to reserve local spike port');
  return selected;
}


async function checkedJson(url, init) {
  const response = await fetch(url, init);
  const text = await response.text();
  if (!response.ok) throw new Error(`${init?.method ?? 'GET'} ${url}: ${response.status} ${text}`);
  return text ? JSON.parse(text) : null;
}


async function waitForServer(url) {
  for (let attempt = 0; attempt < 150; attempt += 1) {
    try {
      const response = await fetch(`${url}/api/version`);
      if (response.ok) return;
    } catch {}
    await delay(100);
  }
  throw new Error('OpenDesign daemon did not become ready');
}


async function waitForAgent(url, id) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const payload = await checkedJson(`${url}/api/agents`);
    if (payload.agents?.some((agent) => agent.id === id && agent.available === true)) return;
    await delay(100);
  }
  throw new Error(`ACP fixture agent ${id} was not detected`);
}


async function readTrace(tracePath) {
  const raw = await readFile(tracePath, 'utf8');
  return raw
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}


async function stopProcessGroup(child) {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
  try { process.kill(-child.pid, 'SIGTERM'); } catch {}
  const exited = await Promise.race([
    new Promise((resolve) => child.once('exit', () => resolve(true))),
    delay(3000).then(() => false),
  ]);
  if (!exited) {
    try { process.kill(-child.pid, 'SIGKILL'); } catch {}
  }
}


function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}


async function runBrowserProof(page) {
  return page.evaluate(async () => {
    const terminal = new Set(['succeeded', 'failed', 'canceled', 'cancelled']);
    const request = async (url, init) => {
      const response = await fetch(url, init);
      const text = await response.text();
      let body = null;
      try { body = text ? JSON.parse(text) : null; } catch { body = text; }
      if (!response.ok) throw new Error(`${init?.method ?? 'GET'} ${url}: ${response.status} ${text}`);
      return { status: response.status, body };
    };
    const waitRun = async (runId, timeoutMs = 15_000) => {
      const started = Date.now();
      while (Date.now() - started < timeoutMs) {
        const { body } = await request(`/api/runs/${encodeURIComponent(runId)}`);
        if (terminal.has(body.status)) return body;
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
      throw new Error(`run ${runId} did not become terminal`);
    };
    const readUntil = async (reader, marker, maxReads = 100) => {
      const decoder = new TextDecoder();
      let text = '';
      for (let index = 0; index < maxReads; index += 1) {
        const part = await reader.read();
        if (part.done) break;
        text += decoder.decode(part.value, { stream: true });
        if (text.includes(marker)) return text;
      }
      throw new Error(`SSE marker not observed: ${marker}`);
    };
    const createRun = async (projectId, conversationId, message) => {
      const { status, body } = await request('/api/runs', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-od-analytics-device-id': 'maverick-g3-spike',
          'x-od-analytics-session-id': 'maverick-g3-browser',
          'x-od-analytics-client-type': 'web',
        },
        body: JSON.stringify({
          projectId,
          conversationId,
          assistantMessageId: `assistant_${crypto.randomUUID()}`,
          clientRequestId: `client_${crypto.randomUUID()}`,
          agentId: 'maverick',
          message,
          currentPrompt: message,
        }),
      });
      return { status, runId: body.runId };
    };

    const projectId = `maverick_g3_${crypto.randomUUID()}`;
    const projectResponse = await request('/api/projects', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        id: projectId,
        name: 'Maverick G3 browser spike',
        metadata: { kind: 'prototype' },
        skipDiscoveryBrief: true,
      }),
    });
    const conversationId = projectResponse.body.conversationId;

    const success = await createRun(projectId, conversationId, 'success');
    const streamResponse = await fetch(`/api/runs/${encodeURIComponent(success.runId)}/events`);
    if (!streamResponse.ok || !streamResponse.body) throw new Error('missing run SSE body');
    const reader = streamResponse.body.getReader();
    await readUntil(reader, 'first-sse-before-terminal');
    const statusAtFirstSse = (await request(`/api/runs/${encodeURIComponent(success.runId)}`)).body.status;
    await reader.cancel();
    const successTerminal = await waitRun(success.runId);
    const successPackage = (await request(`/api/runs/${encodeURIComponent(success.runId)}/result-package`)).body;
    const filesAfterSuccess = (await request(`/api/projects/${encodeURIComponent(projectId)}/files`)).body;

    const resumed = await createRun(projectId, conversationId, 'MAVERICK_SPIKE_RESUME');
    const resumeTerminal = await waitRun(resumed.runId);

    const failure = await createRun(projectId, conversationId, 'MAVERICK_SPIKE_FAIL');
    const failureTerminal = await waitRun(failure.runId);
    const failurePackage = (await request(`/api/runs/${encodeURIComponent(failure.runId)}/result-package`)).body;

    const timeout = await createRun(projectId, conversationId, 'MAVERICK_SPIKE_TIMEOUT');
    const timeoutTerminal = await waitRun(timeout.runId);
    const timeoutPackage = (await request(`/api/runs/${encodeURIComponent(timeout.runId)}/result-package`)).body;

    const canceled = await createRun(projectId, conversationId, 'MAVERICK_SPIKE_LONG');
    const cancelStreamResponse = await fetch(`/api/runs/${encodeURIComponent(canceled.runId)}/events`);
    if (!cancelStreamResponse.ok || !cancelStreamResponse.body) throw new Error('missing cancel SSE body');
    const cancelReader = cancelStreamResponse.body.getReader();
    await readUntil(cancelReader, 'first-sse-before-terminal');
    const cancelOne = await request(`/api/runs/${encodeURIComponent(canceled.runId)}/cancel`, { method: 'POST' });
    const cancelTwo = await request(`/api/runs/${encodeURIComponent(canceled.runId)}/cancel`, { method: 'POST' });
    await cancelReader.cancel();
    const canceledTerminal = await waitRun(canceled.runId);
    const canceledPackage = (await request(`/api/runs/${encodeURIComponent(canceled.runId)}/result-package`)).body;

    const names = Array.isArray(filesAfterSuccess)
      ? filesAfterSuccess.map((entry) => entry.name)
      : Array.isArray(filesAfterSuccess?.files)
        ? filesAfterSuccess.files.map((entry) => entry.name)
        : [];
    return {
      ui: { title: document.title },
      streaming: {
        createStatus: success.status,
        statusAtFirstSse,
        terminalStatus: successTerminal.status,
      },
      fileWrite: { expectedPresent: names.includes('maverick-spike.html') },
      resume: { terminalStatus: resumeTerminal.status },
      failure: { terminalStatus: failureTerminal.status },
      timeout: { terminalStatus: timeoutTerminal.status },
      cancel: {
        firstStatus: cancelOne.status,
        secondStatus: cancelTwo.status,
        terminalStatus: canceledTerminal.status,
      },
      resultPackages: {
        success: successPackage.run.status,
        failure: failurePackage.run.status,
        timeout: timeoutPackage.run.status,
        cancel: canceledPackage.run.status,
      },
    };
  });
}
