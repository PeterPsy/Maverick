import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import ts from "typescript";
import { browserExecutable, close, listen, send } from "./browser-contract-support.mjs";

const cases = [
  { title: "desktop Chat records", owner: "chat", isolated: true, records: true },
  { title: "mobile Chat records", owner: "chat", isolated: true, records: true, mobile: true },
  { title: "Chat widget records", owner: "chat", widget: true, isolated: true, records: true },
  { title: "bare directives block a srcdoc form launch", owner: "chat", records: false },
  { title: "a restrictive shell header blocks even exact delegation", owner: "chat", isolated: true, restrictive: true, records: false },
  { title: "unrelated widgets cannot record", owner: "storage", isolated: true, records: false },
  { title: "navigation to another origin cannot record", owner: "chat", isolated: true, otherOrigin: true, records: false },
];

for (const scenario of cases) {
  test(scenario.title, async (context) => {
    const browser = browserExecutable();
    if (!browser) {
      context.skip("Chromium or Chrome is required for the microphone browser contract.");
      return;
    }
    const profile = mkdtempSync(resolve(tmpdir(), "maverick-microphone-browser-"));
    context.after(() => rmSync(profile, { force: true, recursive: true }));
    const appServer = createServer();
    const shellServer = createServer();
    const otherServer = createServer();
    const report = Promise.withResolvers();
    let browserProcess;
    let timeout;
    let stderr = "";
    try {
      const appOrigin = await listen(appServer);
      const shellOrigin = await listen(shellServer);
      const otherOrigin = await listen(otherServer);
      for (const server of [appServer, otherServer]) {
        server.on("request", (_request, response) => {
          send(response, recordingDocument(shellOrigin), "text/html");
        });
      }
      shellServer.on("request", (request, response) => {
        if (request.url === "/result" && request.method === "POST") {
          let body = "";
          request.on("data", (chunk) => { body += chunk; });
          request.on("end", () => {
            send(response, "ok", "text/plain");
            report.resolve(JSON.parse(body));
          });
          return;
        }
        if (request.url === "/iframePolicy.js" || request.url === "/theme.js") {
          const file = request.url === "/iframePolicy.js" ? "iframePolicy.ts" : "theme.ts";
          const source = readFileSync(resolve(import.meta.dirname, `../frontend/src/${file}`), "utf8");
          const module = ts.transpileModule(source, {
            compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
          }).outputText.replace('from "./theme"', 'from "./theme.js"');
          send(response, module, "text/javascript");
          return;
        }
        send(response, shellDocument(appOrigin, scenario.otherOrigin ? otherOrigin : appOrigin, scenario), "text/html", 200, {
          "Permissions-Policy": scenario.restrictive
            ? "camera=(), microphone=(self), geolocation=()"
            : "camera=(), geolocation=()",
        });
      });
      browserProcess = spawn(browser, [
        "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
        "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
        `--user-data-dir=${profile}`,
        `--window-size=${scenario.mobile ? "390,844" : "1280,800"}`,
        `${shellOrigin}/`,
      ], { stdio: ["ignore", "ignore", "pipe"] });
      browserProcess.stderr.on("data", (chunk) => { stderr += chunk; });
      browserProcess.once("error", report.reject);
      timeout = setTimeout(() => report.reject(new Error(`Microphone browser test timed out. ${stderr}`)), 15_000);
      const result = await report.promise;
      assert.equal(result.records, scenario.records, JSON.stringify(result));
      assert.equal(result.camera, false);
      assert.equal(result.geolocation, false);
      if (scenario.records) {
        assert.ok(result.bytes > 0);
      } else {
        assert.equal(result.error, "NotAllowedError");
      }
    } finally {
      clearTimeout(timeout);
      if (browserProcess && browserProcess.exitCode === null) {
        const stopped = new Promise((resolveExit) => browserProcess.once("exit", resolveExit));
        browserProcess.kill("SIGKILL");
        await stopped;
      }
      await Promise.all([close(appServer), close(shellServer), close(otherServer)]);
    }
  });
}

function shellDocument(appOrigin, targetOrigin, scenario) {
  const relay = `<script>const form=document.createElement('form');form.method='POST';form.action=${JSON.stringify(`${targetOrigin}/record`)};document.body.append(form);form.submit()</script>`;
  return `<!doctype html><html><body><iframe id="app"></iframe><script type="module">
    import { MAVERICK_IFRAME_SANDBOX, appFrameBrowserFeaturePolicy, widgetFrameBrowserFeaturePolicy, isolatedFrameBrowserFeaturePolicy } from '/iframePolicy.js';
    const frame = document.querySelector('#app');
    const features = ${scenario.owner === "chat" && !scenario.widget ? "appFrameBrowserFeaturePolicy" : "widgetFrameBrowserFeaturePolicy"}(${JSON.stringify(scenario.owner)});
    frame.sandbox = MAVERICK_IFRAME_SANDBOX;
    frame.allow = ${scenario.isolated ? `isolatedFrameBrowserFeaturePolicy(features, ${JSON.stringify(appOrigin)})` : "features"};
    addEventListener('message', event => {
      if (event.source !== frame.contentWindow || event.origin !== ${JSON.stringify(targetOrigin)}) return;
      void fetch('/result', { method: 'POST', body: JSON.stringify(event.data) });
    });
    frame.srcdoc = ${JSON.stringify(`<!doctype html><html><body>${relay}</body></html>`).replaceAll("<", "\\u003c")};
  </script></body></html>`;
}

function recordingDocument(shellOrigin) {
  return `<!doctype html><html><body><script>
    (async () => {
      const result = {
        camera: document.featurePolicy.allowsFeature('camera'),
        geolocation: document.featurePolicy.allowsFeature('geolocation'),
        records: false,
        bytes: 0,
      };
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const recorder = new MediaRecorder(stream);
        recorder.ondataavailable = event => { result.bytes += event.data.size; };
        recorder.onstop = () => {
          stream.getTracks().forEach(track => track.stop());
          result.records = result.bytes > 0;
          parent.postMessage(result, ${JSON.stringify(shellOrigin)});
        };
        recorder.start();
        setTimeout(() => recorder.stop(), 300);
      } catch (error) {
        stream?.getTracks().forEach(track => track.stop());
        result.error = error.name;
        parent.postMessage(result, ${JSON.stringify(shellOrigin)});
      }
    })();
  </script></body></html>`;
}
