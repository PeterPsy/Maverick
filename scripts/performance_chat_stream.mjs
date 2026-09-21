/** Full React streaming workload; intercept only the disposable session socket. */
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { baseUrl, chromium, executablePath } from './performance_browser_support.mjs';

const history = JSON.parse(readFileSync(process.env.MAVERICK_PERFORMANCE_CHAT_EVENTS, 'utf8'));
assert.equal(history.length, 4000);
const samples = Number(process.env.MAVERICK_PERFORMANCE_STREAM_TRIALS || 5);
assert(Number.isInteger(samples) && samples >= 1 && samples <= 10);
const tracePath = process.env.MAVERICK_PERFORMANCE_STREAM_TRACE;
if (tracePath) assert.equal(samples, 1, 'Tracing is a separate diagnostic, not a comparison trial.');
const browser = await chromium.launch({ headless: true, executablePath: executablePath() });
const browserMetrics = await browser.newBrowserCDPSession();
const processCpu = async () => (await browserMetrics.send('SystemInfo.getProcessInfo')).processInfo;
const { gpu } = await browserMetrics.send('SystemInfo.getInfo');
const results = [];
const compactEvidence = process.env.MAVERICK_PERFORMANCE_COMPACT === '1';
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const metrics = async cdp => Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(({ name, value }) => [name, value]));
const percentile = (values, fraction) => {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(sorted.length * fraction) - 1)];
};
const statistics = values => ({ min: Math.min(...values), median: percentile(values, 0.5),
  p95: percentile(values, 0.95), max: Math.max(...values) });
try {
  for (let trial = 0; trial < samples; trial++) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    context.setDefaultTimeout(30_000);
    const errors = [];
    let socket;
    let snapshots = 0;
    await context.routeWebSocket(/\/ws\/runtime\/sessions\/performance-chat-history(?:\?|$)/, route => {
      socket = route;
      const server = route.connectToServer();
      server.onMessage(message => {
        const frame = JSON.parse(String(message));
        if (frame.type === 'runtime.snapshot') {
          snapshots++;
          // This synthetic stream never submits a turn or starts a provider.
          // Missing provider credentials in the disposable host must not disable typing.
          route.send(JSON.stringify({ ...frame, session: { ...frame.session, runtime_admission: null },
            runtime_admission: null, events: history, has_more_before: false,
            oldest_event_id: history[0].event_id, last_event_id: history.at(-1).event_id }));
        } else route.send(message);
      });
    });
    await context.addInitScript(() => {
      window.__streamProbe = { firstText: [], input: [], keyEvents: [] };
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) if (entry.name === 'keydown') {
          window.__streamProbe.keyEvents.push({ duration: entry.duration,
            input_delay: entry.processingStart - entry.startTime,
            handler: entry.processingEnd - entry.processingStart });
        }
      }).observe({ type: 'event', durationThreshold: 16, buffered: true });
      const NativeSocket = window.WebSocket;
      window.WebSocket = class extends NativeSocket {
        constructor(...args) {
          super(...args);
          this.addEventListener('message', event => {
            let frame;
            try { frame = JSON.parse(event.data); } catch { return; }
            if (frame.event?.payload?.text !== '**stream-payload** ') return;
            const started = performance.now();
            const observer = new MutationObserver(() => {
              if (![...document.querySelectorAll('.chatapp-agent-block__body')]
                .some(element => element.textContent.includes('stream-payload'))) return;
              observer.disconnect();
              requestAnimationFrame(() => window.__streamProbe.firstText.push(performance.now() - started));
            });
            observer.observe(document.body, { childList: true, subtree: true, characterData: true });
          });
        }
      };
      document.addEventListener('input', () => {
        const started = performance.now();
        requestAnimationFrame(() => requestAnimationFrame(() => window.__streamProbe.input.push(performance.now() - started)));
      });
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    try {
      const login = await context.request.post(`${baseUrl}/api/auth/login`, {
        data: { username: 'fixture-admin', password: 'fixture-only-password' },
      });
      assert(login.ok());
      await page.goto(`${baseUrl}/app/chat?thread_id=performance-chat-thread`, { waitUntil: 'domcontentloaded' });
      const iframe = page.locator('iframe.bs-workspace-app-frame.is-active');
      await iframe.waitFor();
      const chat = await (await iframe.elementHandle()).contentFrame();
      await chat.getByText('Fixture request 00999', { exact: true }).waitFor({ timeout: 60_000 });
      assert(socket, 'Session stream was not intercepted.');
      const cdp = await context.newCDPSession(chat);
      await cdp.send('Performance.enable', { timeDomain: 'threadTicks' });
      let ordinal = 0;
      function send(type, payload, turn = 'measured-stream') {
        socket.send(JSON.stringify({ type: 'runtime.event', event: {
          event_id: `stream-${String(ordinal++).padStart(6, '0')}`, session_id: 'performance-chat-history',
          workspace_id: 'default', turn_id: turn, process_id: null, plane: 'turn', event_type: type,
          created_at: new Date(Date.UTC(2026, 8, 2, 0, 0, 0, ordinal)).toISOString(), payload,
        } }));
      }
      send('runtime.turn.queued', { input_text: 'Warmup rendering' }, 'warmup');
      for (let index = 0; index < 5; index++) { send('runtime.output.delta', { text: 'Warmup. ' }, 'warmup'); await sleep(25); }
      send('runtime.output.final', { text: 'Warmup complete.' }, 'warmup');
      send('runtime.turn.completed', {}, 'warmup');
      await chat.getByText('Warmup complete.', { exact: true }).waitFor();
      const composer = chat.getByRole('textbox').first();
      await composer.click();
      await sleep(500);
      const filteredSurfaces = tracePath ? await chat.evaluate(() => [...document.querySelectorAll('*')]
        .filter(element => getComputedStyle(element).backdropFilter !== 'none')
        .map(element => ({ class: element.className, filter: getComputedStyle(element).backdropFilter,
          width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height }))) : [];
      if (tracePath) await page.screenshot({ path: `${tracePath}.png` });
      const tracer = tracePath ? await context.newCDPSession(page) : null;
      if (tracer) await tracer.send('Tracing.start', {
        categories: 'devtools.timeline,blink.user_timing,benchmark,cc,input', transferMode: 'ReturnAsStream',
      });
      if (tracer) {
        await cdp.send('Profiler.enable');
        await cdp.send('Profiler.start');
      }
      const processesBefore = await processCpu();
      const before = await metrics(cdp);
      const started = performance.now();
      send('runtime.turn.queued', { input_text: 'Measure streaming with typing and scrolling.' });
      let output = '**stream-payload** ';
      send('runtime.output.delta', { text: output });
      const inputActions = [];
      const scrollActions = [];
      const emissionDelays = [];
      const atTime = async offset => { await sleep(Math.max(0, started + offset - performance.now())); };
      const stream = async () => {
        for (let index = 0; index < 500; index++) {
          await atTime(index * 20);
          emissionDelays.push(performance.now() - started - index * 20);
          const chunk = `${String(index).padStart(4, '0')} `;
          output += chunk;
          send('runtime.output.delta', { text: chunk });
          if (index % 100 === 99) send('runtime.tool_call.completed', {
            tool_name: 'fixture.inspect', invocation_id: `stream-tool-${index}`, output: 'Verified fixture.',
          });
        }
      };
      const interact = async () => {
        for (let index = 0; index < 20; index++) {
          await atTime(250 + index * 500);
          const at = performance.now();
          await composer.press('x');
          inputActions.push(performance.now() - at);
          if (index % 2 === 1) {
            const box = await chat.locator('.chatapp-chat-scroll__inner').boundingBox();
            await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
            const scrolled = performance.now();
            await page.mouse.wheel(0, index % 4 === 1 ? -300 : 300);
            scrollActions.push(performance.now() - scrolled);
          }
        }
      };
      const operations = await Promise.allSettled([stream(), interact()]);
      for (const operation of operations) if (operation.status === 'rejected') throw operation.reason;
      const finalText = 'Stream complete. All chunks verified.';
      send('runtime.output.final', { text: finalText });
      send('runtime.turn.completed', {});
      await chat.locator('.chatapp-chat-scroll__inner').evaluate(element => { element.scrollTop = element.scrollHeight; });
      await chat.getByText(finalText, { exact: true }).waitFor();
      const bodies = await chat.locator('.chatapp-agent-block__body').allTextContents();
      const firstOutput = bodies.findIndex(text => text.startsWith('stream-payload'));
      assert(firstOutput >= 0, 'Initial stream output was lost.');
      const rendered = bodies.slice(firstOutput).join(' ').replace(/\s+/g, ' ').trim();
      const expected = `${output.replaceAll('**', '')}${finalText}`;
      assert.equal(rendered, expected, 'All 500 chunks must survive tool boundaries and terminal flush.');
      await chat.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const after = await metrics(cdp);
      const processesAfter = await processCpu();
      const previousCpu = new Map(processesBefore.map(item => [item.id, item.cpuTime]));
      const remainingIds = new Set(processesAfter.map(item => item.id));
      assert(processesBefore.every(item => remainingIds.has(item.id)), 'A browser process exited during measurement.');
      const processDeltas = processesAfter.map(item => ({ type: item.type,
        cpu_ms: (item.cpuTime - (previousCpu.get(item.id) ?? 0)) * 1000 }));
      if (tracer) {
        const { profile } = await cdp.send('Profiler.stop');
        writeFileSync(`${tracePath}.cpuprofile`, JSON.stringify(profile));
        const complete = new Promise(resolve => tracer.once('Tracing.tracingComplete', resolve));
        await tracer.send('Tracing.end');
        const { stream } = await complete;
        const chunks = [];
        while (true) {
          const chunk = await tracer.send('IO.read', { handle: stream });
          chunks.push(Buffer.from(chunk.data, chunk.base64Encoded ? 'base64' : 'utf8'));
          if (chunk.eof) break;
        }
        await tracer.send('IO.close', { handle: stream });
        writeFileSync(tracePath, Buffer.concat(chunks));
      }
      await sleep(150); // Event Timing is delivered asynchronously after paint.
      const timings = await chat.evaluate(() => window.__streamProbe);
      assert.equal(await composer.innerText(), 'x'.repeat(20));
      assert.equal(snapshots, 1, 'Unexpected reconnect changes the workload.');
      assert.equal(timings.firstText.length, 1);
      assert.equal(timings.input.length, 20);
      assert.deepEqual(errors, []);
      results.push({ trial, elapsed_ms: performance.now() - started,
        browser_cpu_ms: processDeltas.reduce((sum, item) => sum + item.cpu_ms, 0), browser_process_cpu: processDeltas,
        main_thread_cpu_ms: (after.TaskDuration - before.TaskDuration) * 1000,
        script_ms: (after.ScriptDuration - before.ScriptDuration) * 1000,
        layout_ms: (after.LayoutDuration - before.LayoutDuration) * 1000,
        heap_used_bytes: after.JSHeapUsedSize, nodes: after.Nodes,
        first_text_frame_ms: timings.firstText[0], input_next_frame_ms: timings.input,
        key_event_timing: timings.keyEvents, key_event_reporting_threshold_ms: 16,
        input_action_ms: inputActions, scroll_action_ms: scrollActions,
        emission_delay_ms: emissionDelays,
        filtered_surfaces: filteredSurfaces,
        output_sha256: createHash('sha256').update(rendered).digest('hex'), output_characters: rendered.length,
        input_preserved: true, errors });
      process.stderr.write(`Streaming trial ${trial + 1}/${samples} finished.\n`);
    } finally { await context.close(); }
  }
  const scalarMetrics = ['elapsed_ms', 'browser_cpu_ms', 'main_thread_cpu_ms', 'script_ms', 'layout_ms',
    'heap_used_bytes', 'nodes', 'first_text_frame_ms'];
  const summary = Object.fromEntries(scalarMetrics.map(key => [key, statistics(results.map(result => result[key]))]));
  const processTypes = [...new Set(results.flatMap(result => result.browser_process_cpu.map(process => process.type)))];
  summary.browser_process_cpu_ms = Object.fromEntries(processTypes.map(type => [type, statistics(results.map(result =>
    result.browser_process_cpu.filter(process => process.type === type).reduce((sum, process) => sum + process.cpu_ms, 0)))]));
  summary.input_action_ms = statistics(results.flatMap(result => result.input_action_ms));
  summary.input_next_frame_ms = statistics(results.flatMap(result => result.input_next_frame_ms));
  summary.scroll_action_ms = statistics(results.flatMap(result => result.scroll_action_ms));
  const evidenceResults = compactEvidence ? results.map(result => ({
    trial: result.trial,
    elapsed_ms: result.elapsed_ms,
    browser_cpu_ms: result.browser_cpu_ms,
    browser_process_cpu_ms: Object.fromEntries(processTypes.map(type => [type,
      result.browser_process_cpu.filter(process => process.type === type).reduce((sum, process) => sum + process.cpu_ms, 0)])),
    main_thread_cpu_ms: result.main_thread_cpu_ms,
    script_ms: result.script_ms,
    layout_ms: result.layout_ms,
    heap_used_bytes: result.heap_used_bytes,
    nodes: result.nodes,
    first_text_frame_ms: result.first_text_frame_ms,
    input_action_ms: statistics(result.input_action_ms),
    input_next_frame_ms: statistics(result.input_next_frame_ms),
    scroll_action_ms: statistics(result.scroll_action_ms),
    output_sha256: result.output_sha256,
    output_characters: result.output_characters,
    input_preserved: result.input_preserved,
    errors: result.errors,
  })) : results;
  process.stdout.write(JSON.stringify({ schema: 1, boundary: 'chromium-browser-and-isolated-chat-frame',
    browser: browser.version(), graphics: { devices: gpu.devices, renderer: gpu.auxAttributes?.glRenderer },
    history_turns: 1000, history_events: 4000,
    warmup_deltas: 5, measured_deltas: 501, interval_ms: 20, tool_completions: 5,
    transport: 'real authenticated host with deterministic session WebSocket interception',
    physical_device_gate: 'not-tested', diagnostic_tracing: Boolean(tracePath), compact_evidence: compactEvidence,
    summary, results: evidenceResults }, null, 2) + '\n');
} finally { await browser.close(); }
