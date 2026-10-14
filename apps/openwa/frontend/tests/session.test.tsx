import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { operation } from "../src/api";
import { SessionPanel } from "../src/SessionPanel";

vi.mock("../src/api", async (original) => ({ ...await original(), operation: vi.fn() }));
vi.mock("@loopino/pwa-cache", () => ({
  loopinoAppIsVisible: () => true,
  observeLoopinoVisibility: (listener: (visible: boolean) => void) => { listener(true); return () => {}; },
}));
const session = { id: "one", name: "Phone", status: "qr_ready", engineLoaded: true };
let container: HTMLDivElement;
let root: Root;
const request = vi.mocked(operation);
const props = { session, canManage: true, onClose: () => {}, onRefresh: () => {} };
beforeEach(() => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  request.mockReset().mockResolvedValue({ qrCode: "data:image/png;base64,aGVsbG8=" });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); });

it("removes an obsolete QR and shows a recoverable QR error", async () => {
  await act(async () => root.render(<SessionPanel {...props} />));
  expect(container.querySelector(".qr-card img")).not.toBeNull();
  request.mockRejectedValueOnce(new Error("Gateway unavailable"));
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(container.querySelector(".qr-card img")).toBeNull();
  expect(container.textContent).toContain("Gateway unavailable");
  const retry = [...container.querySelectorAll("button")].find((button) => button.textContent === "Retry QR")!;
  await act(async () => retry.click());
  expect(container.querySelector(".qr-card img")).not.toBeNull();
  expect(container.textContent).not.toContain("Gateway unavailable");
});

it("cancels a pending QR read when the session becomes ready", async () => {
  let finish!: (data: unknown) => void;
  request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await act(async () => root.render(<SessionPanel {...props} />));
  const signal = request.mock.calls[0][2]!;
  await act(async () => root.render(<SessionPanel {...props} session={{ ...session, status: "ready" }} />));
  expect(signal.aborted).toBe(true);
  await act(async () => { finish({ qrCode: "data:image/png;base64,aGVsbG8=" }); await vi.advanceTimersByTimeAsync(15000); });
  expect(container.querySelector(".qr-card img")).toBeNull();
  expect(request).toHaveBeenCalledTimes(1);
});
