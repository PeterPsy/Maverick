import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useMaverickHost } from "../src/host";

const bridge = vi.hoisted(() => ({ trusted: true, listener: (_event: unknown) => {} }));
vi.mock("@maverick/pwa-cache", () => ({
  maverickAppIsVisible: () => true,
  isExactMaverickParentMessage: () => bridge.trusted,
  connectAppEventSocket: (listener: (event: unknown) => void) => { bridge.listener = listener; return () => {}; },
}));
const refresh = vi.fn(), navigate = vi.fn();
let root: Root;
function Probe() { useMaverickHost(refresh, navigate); return null; }
async function message(data: unknown) {
  await act(async () => window.dispatchEvent(new MessageEvent("message", { data })));
}
beforeEach(async () => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  bridge.trusted = true;
  delete document.documentElement.dataset.maverickTheme;
  root = createRoot(document.createElement("div"));
  await act(async () => root.render(<Probe />));
});
afterEach(async () => { await act(async () => root.unmount()); });

it("accepts live theme on navigation and theme changes only from the trusted parent", async () => {
  await message({ type: "maverick.app.navigate", app_id: "openwa", theme: { effective: "light" } });
  expect(document.documentElement.dataset.maverickTheme).toBe("light");
  expect(document.documentElement.style.colorScheme).toBe("light");
  bridge.trusted = false;
  await message({ type: "maverick.shell.theme-changed", theme: { effective: "dark" } });
  expect(document.documentElement.dataset.maverickTheme).toBe("light");
  bridge.trusted = true;
  await message({ type: "unrelated", theme: { effective: "dark" } });
  expect(document.documentElement.dataset.maverickTheme).toBe("light");
  await message({ type: "maverick.shell.theme-changed", theme: { effective: "dark" } });
  expect(document.documentElement.dataset.maverickTheme).toBe("dark");
});

it("bounds session navigation and rejects another app's selection", async () => {
  await message({ type: "maverick.app.navigate", app_id: "openwa", params: { session_id: "phone_1" } });
  expect(navigate).toHaveBeenCalledWith("phone_1");
  navigate.mockClear();
  for (const session_id of ["../other", "x".repeat(129), ""]) {
    await message({ type: "maverick.app.navigate", app_id: "openwa", params: { session_id } });
  }
  await message({ type: "maverick.app.navigate", app_id: "other", params: { session_id: "phone_1" } });
  expect(navigate).not.toHaveBeenCalled();
});

it("refreshes connection and session changes without fetching on inbox-only events", async () => {
  await act(async () => {
    for (const resource of ["connection", "sessions", "notifications", "messages"])
      bridge.listener({ type: "maverick.app.data-changed", owner_app_id: "openwa", resource });
    bridge.listener({ type: "maverick.app.data-changed", owner_app_id: "other", resource: "sessions" });
  });
  expect(refresh).toHaveBeenCalledTimes(2);
});
