import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useLoopinoHost } from "../src/host";

const bridge = vi.hoisted(() => ({ trusted: true, listener: (_event: unknown) => {} }));
vi.mock("@loopino/pwa-cache", () => ({
  loopinoAppIsVisible: () => true,
  isExactLoopinoParentMessage: () => bridge.trusted,
  connectAppEventSocket: (listener: (event: unknown) => void) => { bridge.listener = listener; return () => {}; },
}));
const refresh = vi.fn(), navigate = vi.fn();
let root: Root;
function Probe() { useLoopinoHost(refresh, navigate); return null; }
async function message(data: unknown) {
  await act(async () => window.dispatchEvent(new MessageEvent("message", { data })));
}
beforeEach(async () => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  bridge.trusted = true;
  delete document.documentElement.dataset.loopinoTheme;
  root = createRoot(document.createElement("div"));
  await act(async () => root.render(<Probe />));
});
afterEach(async () => { await act(async () => root.unmount()); });

it("prevents Backspace navigation from the page and locked message fields", async () => {
  const button = document.createElement("button");
  const locked = document.createElement("textarea");
  locked.value = "Unconfirmed send";
  locked.readOnly = true;
  document.body.append(button, locked);
  try {
    for (const target of [document.body, button, locked]) {
      for (const shiftKey of [false, true]) {
        const event = new KeyboardEvent("keydown", { key: "Backspace", shiftKey, bubbles: true, cancelable: true });
        target.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(true);
      }
    }
    expect(locked.value).toBe("Unconfirmed send");
    locked.readOnly = false;
    locked.disabled = true;
    const event = new KeyboardEvent("keydown", { key: "Backspace", bubbles: true, cancelable: true });
    locked.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  } finally { button.remove(); locked.remove(); }
});

it("leaves text deletion, modifiers and explicit browser navigation to their controls", async () => {
  const input = document.createElement("input");
  const textarea = document.createElement("textarea");
  const editor = document.createElement("div");
  editor.contentEditable = "true";
  document.body.append(input, textarea, editor);
  try {
    for (const target of [input, textarea, editor]) {
      const event = new KeyboardEvent("keydown", { key: "Backspace", bubbles: true, cancelable: true });
      target.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false);
    }
    for (const options of [{ key: "Delete" }, { key: "ArrowLeft", altKey: true },
      { key: "Backspace", ctrlKey: true }, { key: "Backspace", metaKey: true }, { key: "Backspace", altKey: true }]) {
      const event = new KeyboardEvent("keydown", { ...options, bubbles: true, cancelable: true });
      document.body.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false);
    }
  } finally { input.remove(); textarea.remove(); editor.remove(); }
});

it("removes keyboard protection when the app unmounts", async () => {
  await act(async () => root.render(null));
  const event = new KeyboardEvent("keydown", { key: "Backspace", bubbles: true, cancelable: true });
  document.body.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(false);
});

it("accepts live theme on navigation and theme changes only from the trusted parent", async () => {
  await message({ type: "loopino.app.navigate", app_id: "openwa", theme: { effective: "light" } });
  expect(document.documentElement.dataset.loopinoTheme).toBe("light");
  expect(document.documentElement.style.colorScheme).toBe("light");
  bridge.trusted = false;
  await message({ type: "loopino.shell.theme-changed", theme: { effective: "dark" } });
  expect(document.documentElement.dataset.loopinoTheme).toBe("light");
  bridge.trusted = true;
  await message({ type: "unrelated", theme: { effective: "dark" } });
  expect(document.documentElement.dataset.loopinoTheme).toBe("light");
  await message({ type: "loopino.shell.theme-changed", theme: { effective: "dark" } });
  expect(document.documentElement.dataset.loopinoTheme).toBe("dark");
});

it("bounds session navigation and rejects another app's selection", async () => {
  await message({ type: "loopino.app.navigate", app_id: "openwa", params: { session_id: "phone_1" } });
  expect(navigate).toHaveBeenCalledWith("phone_1");
  navigate.mockClear();
  for (const session_id of ["../other", "x".repeat(129), ""]) {
    await message({ type: "loopino.app.navigate", app_id: "openwa", params: { session_id } });
  }
  await message({ type: "loopino.app.navigate", app_id: "other", params: { session_id: "phone_1" } });
  expect(navigate).not.toHaveBeenCalled();
});

it("refreshes connection and session changes without fetching on inbox-only events", async () => {
  await act(async () => {
    for (const resource of ["connection", "sessions", "notifications", "messages"])
      bridge.listener({ type: "loopino.app.data-changed", owner_app_id: "openwa", resource });
    bridge.listener({ type: "loopino.app.data-changed", owner_app_id: "other", resource: "sessions" });
  });
  expect(refresh).toHaveBeenCalledTimes(2);
});
