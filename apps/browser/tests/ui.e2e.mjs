// Owned, offline UI fixtures. No platform cookies or real shared tabs are used.
import {chromium} from "playwright";
import assert from "node:assert/strict";
import {readFileSync, existsSync} from "node:fs";
import {resolve, extname} from "node:path";
import {fileURLToPath} from "node:url";

const dist = fileURLToPath(new URL("../frontend/dist/", import.meta.url));
const origin = "http://browser-fixture.test";
const now = Date.now() / 1000;
const overview = {workspace_id: "fixture", connections: [{session_id: "chrome-fixture", title: "Fixture profile",
  display_name: "Chrome", status: "connected", sharing_mode: "agent_tab", allowed_platforms: ["instagram", "youtube"], platform: "instagram", url: "https://www.instagram.com/fixture/", last_seen: now}],
  operations: [{operation_id: "op-fixture", session_id: "chrome-fixture", action: "content.read", status: "running", created_at: now}]};
let denyDisconnect = true;
let operationResult;
const browser = await chromium.launch({headless: true});
try {
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  await context.route(`${origin}/**`, async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path === "/api/apps/browser/backend") {
      const body = request.postDataJSON(); let result = {}, status = 200;
      if (body.action === "companion.overview") result = overview;
      if (body.action === "operation.cancel") overview.operations[0].status = "cancelled";
      if (body.action === "operation.get" || body.action === "research.open") result = {status: "completed", title: "Fixture result",
        text: "Observed <script>untrusted()</script> text", url: "https://example.com/",
        links: [{url: "javascript:alert(1)", text: "Unsafe link"}, {url: "https://example.com/source", text: "Observed source"}], base64: "fixture-media"};
      if (body.action === "operation.get" && operationResult) result = operationResult;
      if (body.action === "status") result = {broker: {status: "ready"}, sessions: []};
      if (body.action === "companion.disconnect") {
        if (denyDisconnect) {status = 403; result = {error: "fixture_denial", detail: "Sharing could not be stopped."};}
        else overview.connections[0].status = "revoked";
      }
      return route.fulfill({status, contentType: "application/json", body: JSON.stringify(result)});
    }
    const relative = path.replace(/^\/apps\/browser\//u, "") || "index.html";
    const file = resolve(dist, relative);
    if (!file.startsWith(dist) || !existsSync(file)) return route.fulfill({status: 404});
    const contentType = ({".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"})[extname(file)] || "application/octet-stream";
    return route.fulfill({contentType, body: readFileSync(file)});
  });
  const page = await context.newPage(), errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`${origin}/apps/browser/`);
  await page.waitForFunction(() => document.querySelector("#agent-state")?.textContent === "Connected");
  assert.equal(await page.getByRole("button", {name: "Shared tabs", exact: true}).count(), 0);
  assert.equal(await page.getByRole("button", {name: "Browser Lab", exact: true}).count(), 0);
  assert.equal(await page.locator("#setup").getAttribute("open"), null);
  const button = await page.locator("#connections button").elementHandle();
  await button.focus(); overview.connections[0].last_seen++;
  await page.locator("#refresh").dispatchEvent("click");
  await page.waitForFunction(() => !document.querySelector("#refresh").disabled);
  assert.ok(await button.evaluate(element => element === document.querySelector("#connections button") && element === document.activeElement));
  await page.locator("#connections button").click();
  await page.waitForSelector("#error:not([hidden])");
  assert.equal(await page.locator("#error").textContent(), "Sharing could not be stopped.");
  assert.equal(await page.locator("#connections button").isEnabled(), true);
  await page.getByRole("button", {name: "Activity", exact: true}).click();
  await page.locator("#operations button").click();
  await page.waitForFunction(() => document.querySelector("#operations button")?.textContent === "View result");
  await page.locator("#operations button").click();
  await page.waitForSelector("dialog[open]");
  assert.equal(await page.locator(".observed-text").textContent(), "Observed <script>untrusted()</script> text");
  await page.locator(".result-details summary").first().click();
  assert.equal(await page.locator("dialog a[href^='javascript:']").count(), 0);
  assert.equal(await page.getByRole("link", {name: "Observed source"}).count(), 1);
  await page.getByText("Technical details", {exact: true}).click();
  await page.waitForFunction(() => document.querySelector("dialog .result-details:last-child pre"));
  assert.ok(!(await page.locator("dialog .result-details:last-child pre").textContent()).includes("fixture-media"));
  await page.getByRole("button", {name: "Close", exact: true}).click();
  const image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=";
  for (const action of ["screenshot", "video.frame"]) {
    for (const payload of [{base64: image}, {encoding: "base64", data: image}]) {
      operationResult = {action, status: "completed", result: {mime_type: "image/png", ...payload, width: 1, height: 1, time_seconds: 2.5}};
      await page.locator("#operations button").click();
      await page.waitForFunction(() => document.querySelector("dialog img")?.naturalWidth === 1);
      const url = await page.locator("dialog img").getAttribute("src"); assert(url.startsWith("blob:"));
      assert((await page.locator("dialog figcaption").textContent()).includes("2.5s"));
      await page.getByText("Technical details", {exact: true}).click();
      await page.waitForSelector("dialog .result-details pre");
      assert(!(await page.locator("dialog .result-details pre").textContent()).includes(image));
      await page.getByRole("button", {name: "Close", exact: true}).click();
      await page.waitForSelector("dialog", {state: "detached"});
      assert.equal(await page.evaluate(url => fetch(url).then(() => true, () => false), url), false, "Closing a result releases the media object URL");
    }
  }
  operationResult = {action: "video.analyze", status: "completed", result: {duration_seconds: 20, covered_seconds: 10, truncated: true,
    frames: [{mime_type: "image/png", base64: image, time_seconds: 0}, {time_seconds: 9.95, storage: {file_id: "saved-frame"}}],
    audio: {duration_seconds: 10, storage: {file_id: "saved-audio"}}, transcription: {status: "unavailable"}, coverage: "Sampled frames and captured audio."}};
  await page.locator("#operations button").click(); await page.waitForSelector("dialog[open]");
  assert.equal(await page.locator(".result-frame").count(), 2);
  assert.equal(await page.getByRole("link", {name: "Open saved frame in Storage"}).getAttribute("href"), `${origin}/app/storage?file_id=saved-frame`);
  assert.equal(await page.getByRole("link", {name: "Open saved audio in Storage"}).count(), 1);
  assert((await page.locator(".result-media").textContent()).includes("10s observed · 20s duration"));
  await page.getByRole("button", {name: "Close", exact: true}).click();
  operationResult = {action: "content.collect", status: "completed", result: {items: [{url: "https://example.com/post", text: "Observed <script>post</script>", kind: "video", content_observed: false}],
    batches: 3, stop_reason: "item_limit", sections: [{source_url: "https://example.com/", status: "observed", batches: 3, stop_reason: "section_item_limit"}],
    coverage: "Links found during bounded scrolling; feed coverage is partial."}};
  await page.locator("#operations button").click(); await page.waitForSelector("dialog[open]");
  assert((await page.locator(".result-collection").textContent()).includes("1 collected items"));
  assert((await page.locator(".result-collection").textContent()).includes("Stopped: item limit"));
  assert((await page.locator(".result-items").textContent()).includes("item content has not been read"));
  assert.equal(await page.locator(".result-coverage").textContent(), operationResult.result.coverage);
  assert.equal(await page.locator("dialog script").count(), 0);
  await page.getByRole("button", {name: "Close", exact: true}).click(); operationResult = null;
  await page.locator("#filter").selectOption("active");
  assert.equal(await page.locator("#operations .row").count(), 0);
  await page.locator("#filter").selectOption("all");
  await page.locator("#search").fill("missing");
  assert.equal(await page.locator("#operations .row").count(), 0);
  await page.locator("#search").fill("Fixture profile");
  assert.equal(await page.locator("#operations .row").count(), 1);
  await page.getByRole("button", {name: "Agent tab", exact: true}).click();
  denyDisconnect = false; await page.locator("#connections button").click();
  await page.waitForFunction(() => document.querySelector("#agent-state")?.textContent === "Not connected");
  assert.equal(await page.locator("#connections button").isVisible(), false);
  await page.locator("#setup > summary").click();
  await page.locator(".connection-settings > summary").click();
  for (const width of [390, 320]) {
    await page.setViewportSize({width, height: 844});
    const mark = await page.locator(".app-mark").boundingBox(), title = await page.locator("h1").boundingBox();
    assert.ok(title.x >= mark.x + mark.width, `Header overlap at ${width}px`);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Page overflow at ${width}px`);
    for (const selector of ["nav", "#refresh", "#show-setup", "#url"]) {
      const box = await page.locator(selector).boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= width, `${selector} clipped at ${width}px`);
    }
  }
  await page.evaluate(() => window.postMessage({type: "maverick.shell.theme-changed", theme: {effective: "light", mode: "light", color_scheme: "light"}}, location.origin));
  await page.waitForFunction(() => document.documentElement.dataset.maverickTheme === "light");
  assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme), "light");
  assert.deepEqual(errors, []);
  await context.close();
  process.stdout.write("Browser UI fixtures passed: agent-focused navigation/readiness, focus, actions, filters, text/images/video/collections, media cleanup, 320/390px layout and theme messages.\n");
} finally { await browser.close(); }
