// Cross-origin shell fixture with platform-served bundles and protected app routes.
import {chromium} from "playwright";
import assert from "node:assert/strict";
import {readFileSync, existsSync} from "node:fs";
import {resolve, extname} from "node:path";
import {fileURLToPath} from "node:url";

const dist = fileURLToPath(new URL("../frontend/dist/", import.meta.url));
const platform = "https://platform-fixture.test", isolated = "https://isolated-fixture.test";
let reads = 0;
const browser = await chromium.launch({headless: true});
try {
  const context = await browser.newContext({acceptDownloads: true});
  await context.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    const cors = {"Access-Control-Allow-Origin": isolated};
    if (url.origin === platform && url.pathname === "/app/browser") return route.fulfill({contentType: "text/html", body:
      `<iframe src="${isolated}/apps/browser/?maverick_theme=light&maverick_color_scheme=light" style="width:100%;height:800px"></iframe>`});
    if (url.origin === platform && !url.pathname.startsWith("/apps/browser/assets/")) return route.fulfill({status: 403, body: "app_frame_isolation_required"});
    if (url.pathname === "/api/apps/browser/backend") {
      assert.equal(url.origin, isolated);
      assert.equal(request.postDataJSON().action, "companion.overview"); reads++;
      return route.fulfill({contentType: "application/json", body: JSON.stringify({connections: [], operations: [], pending_count: 1})});
    }
    const relative = url.pathname.replace(/^\/apps\/browser\//u, "") || "index.html", file = resolve(dist, relative);
    if (!file.startsWith(dist) || !existsSync(file)) return route.fulfill({status: 404});
    let body = readFileSync(file);
    if (extname(file) === ".html") body = Buffer.from(body.toString().replace("<head>", `<head><script>window.__MAVERICK_PLATFORM_ORIGIN__=${JSON.stringify(platform)}</script>`)
      .replaceAll('"/apps/browser/assets/', `"${platform}/apps/browser/assets/`));
    return route.fulfill({headers: cors, contentType: ({".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"})[extname(file)] || "application/octet-stream", body});
  });
  const page = await context.newPage(), errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.clock.install();
  await page.goto(`${platform}/app/browser`);
  const frame = page.frame({url: url => url.origin === isolated});
  await frame.waitForSelector("#url");
  await frame.waitForFunction(() => document.querySelector("#tab-count").textContent === "0");
  assert.equal(await frame.evaluate(() => getComputedStyle(document.documentElement).colorScheme), "light");
  assert.equal(new URL(await frame.locator("#url").inputValue()).origin, isolated);
  assert.equal(await frame.locator("#download").getAttribute("href"), `${isolated}/apps/browser/maverick-browser-companion.zip`);
  // Native downloads are verified against the HTTP server in companion.e2e;
  // route interception cannot fulfill Chromium's browser-process download.
  const archive = await frame.evaluate(async () => {
    const response = await fetch(document.querySelector("#download").href, {credentials: "same-origin"});
    return {status: response.status, bytes: [...new Uint8Array(await response.arrayBuffer())]};
  });
  assert.equal(archive.status, 200);
  assert(Buffer.from(archive.bytes).equals(readFileSync(resolve(dist, "maverick-browser-companion.zip"))));
  const send = message => page.evaluate(({message, isolated}) => document.querySelector("iframe").contentWindow.postMessage(message, isolated), {message, isolated});
  await send({type: "maverick.shell.theme-changed", theme: {effective: "dark", color_scheme: "dark", mode: "dark"}});
  await frame.waitForFunction(() => document.documentElement.dataset.maverickTheme === "dark");
  await frame.evaluate(() => window.postMessage({type: "maverick.shell.theme-changed", theme: {effective: "light"}}, location.origin));
  await page.clock.runFor(1);
  assert.equal(await frame.evaluate(() => document.documentElement.dataset.maverickTheme), "dark", "Messages from a non-parent source are rejected");
  await send({type: "maverick.app.visibility-changed", app_id: "browser", visible: false});
  await page.clock.runFor(1);
  const hiddenReads = reads;
  await page.evaluate(() => document.querySelector("iframe").style.display = "none");
  await frame.locator("#refresh").dispatchEvent("click");
  await send({type: "maverick.app.data-changed", owner_app_id: "browser", resource: "companion"});
  await page.clock.runFor(90000);
  assert.equal(reads, hiddenReads, "Hidden app frames must not poll or refresh on data events");
  assert.equal(await frame.evaluate(() => document.visibilityState), "visible", "Shell hiding does not change document visibility");
  await page.evaluate(() => document.querySelector("iframe").style.display = "block");
  const resumed = page.waitForResponse(response => response.url().endsWith("/api/apps/browser/backend"));
  await send({type: "maverick.app.visibility-changed", app_id: "browser", visible: true});
  await resumed;
  await frame.waitForFunction(() => !document.querySelector("#refresh").disabled);
  assert.equal(reads, hiddenReads + 1, "Showing the app refreshes immediately once");
  await send({type: "maverick.shell.theme-changed", theme: {effective: "light", color_scheme: "light", mode: "system"}});
  await frame.waitForFunction(() => document.documentElement.dataset.maverickTheme === "light");
  assert.deepEqual(errors, []);
  await context.close();
  process.stdout.write("Browser platform fixture passed: isolated download/address, initial/live theme, authenticated parent messages, hidden-frame pause and resume.\n");
} finally { await browser.close(); }
