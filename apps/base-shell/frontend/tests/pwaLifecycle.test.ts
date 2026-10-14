// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";

vi.mock("../src/pwaCacheRuntime", () => ({ shellPwaMetrics: { recordServiceWorker: vi.fn() } }));
vi.mock("../src/shellAuthorization", () => ({ reportShellAuthorizationFailure: vi.fn() }));
const originalServiceWorker = Object.getOwnPropertyDescriptor(navigator, "serviceWorker");

afterEach(() => {
  if (originalServiceWorker) Object.defineProperty(navigator, "serviceWorker", originalServiceWorker);
  else delete (navigator as { serviceWorker?: unknown }).serviceWorker;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function setup(controlled: boolean) {
  vi.stubEnv("PROD", true);
  vi.spyOn(document, "readyState", "get").mockReturnValue("complete");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    schema: "loopino.pwa-config.v2", service_worker: { enabled: true, generation: "v2" },
  }))));
  const waiting = { postMessage: vi.fn() };
  const registration = Object.assign(new EventTarget(), { waiting, update: vi.fn(async () => {}) });
  const worker = Object.assign(new EventTarget(), {
    controller: controlled ? { postMessage: vi.fn() } : null,
    register: vi.fn(async () => registration),
  });
  Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: worker });
  const reload = vi.spyOn(window.location, "reload").mockImplementation(() => {});
  const pwa = await import("../src/pwa");
  pwa.registerShellServiceWorker();
  await vi.waitFor(() => expect(registration.update).toHaveBeenCalledOnce());
  return { worker, waiting, reload, pwa };
}

it.each([true, false])("keeps the document on unsolicited controller changes (controlled=%s)", async controlled => {
  const { worker, reload } = await setup(controlled);
  worker.dispatchEvent(new Event("controllerchange"));
  worker.dispatchEvent(new Event("controllerchange"));
  expect(reload).not.toHaveBeenCalled();
});

it("reloads once only after this document explicitly applies a waiting update", async () => {
  const { worker, waiting, reload, pwa } = await setup(true);
  await expect(pwa.applyShellServiceWorkerUpdate()).resolves.toBe(true);
  expect(waiting.postMessage).toHaveBeenCalledWith({ type: "LOOPINO_SKIP_WAITING" });
  expect(reload).not.toHaveBeenCalled();
  worker.dispatchEvent(new Event("controllerchange"));
  worker.dispatchEvent(new Event("controllerchange"));
  expect(reload).toHaveBeenCalledOnce();
});
