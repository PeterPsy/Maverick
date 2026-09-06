// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ loadCachedCatalog: vi.fn(), requestJson: vi.fn() }));
vi.mock("../../../app-store/frontend/src/assets/appStoreApi.js", () => api);

afterEach(() => { document.body.innerHTML = ""; vi.restoreAllMocks(); });

it("routes only exact-parent catalog recovery to App Store display reads, never installation authority", async () => {
  const template = document.createElement("template");
  template.innerHTML = readFileSync(resolve(import.meta.dirname, "../../../app-store/frontend/src/index.html"), "utf8");
  template.content.querySelectorAll("script, link").forEach((element) => element.remove());
  document.body.replaceChildren(template.content);
  api.loadCachedCatalog.mockResolvedValue({ payload: { items: [] }, revision: "one", source: "network" });
  api.requestJson.mockResolvedValue({ items: [], pinned_apps: [] });
  await import("../../../app-store/frontend/src/assets/main.js");
  await vi.waitFor(() => expect(api.loadCachedCatalog).toHaveBeenCalledOnce());
  const authorityReads = api.requestJson.mock.calls.length;
  const recovery = { type: "maverick.app.data-changed", owner_app_id: "app-store", resource: "records" };
  window.dispatchEvent(new MessageEvent("message", { data: recovery, origin: "https://unregistered.test", source: window }));
  expect(api.loadCachedCatalog).toHaveBeenCalledOnce();
  window.dispatchEvent(new MessageEvent("message", { data: recovery, origin: window.location.origin, source: window }));
  await vi.waitFor(() => expect(api.loadCachedCatalog).toHaveBeenCalledTimes(2));
  expect(api.requestJson).toHaveBeenCalledTimes(authorityReads);
});
