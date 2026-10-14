import { act, useCallback } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useVisiblePolling } from "../src/useVisiblePolling";

const visibility = vi.hoisted(() => ({ visible: true, listener: (_visible: boolean) => {} }));
vi.mock("@loopino/pwa-cache", () => ({
  loopinoAppIsVisible: () => visibility.visible,
  observeLoopinoVisibility: (listener: (visible: boolean) => void) => {
    visibility.listener = listener;
    listener(visibility.visible);
    return () => {};
  },
}));

let container: HTMLDivElement;
let root: Root;
let refresh: () => Promise<void>;
const read = vi.fn<(signal: AbortSignal) => Promise<boolean | void>>();
function Probe({ query = "first", enabled = true }) {
  const load = useCallback((signal: AbortSignal) => read(signal), [query]);
  refresh = useVisiblePolling(load, 1000, enabled);
  return null;
}
beforeEach(() => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  visibility.visible = true;
  read.mockReset().mockResolvedValue();
  container = document.createElement("div");
  root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); vi.useRealTimers(); });

it("waits for a slow read to finish before scheduling the next poll", async () => {
  let finish!: () => void;
  read.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await act(async () => root.render(<Probe />));
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(read).toHaveBeenCalledTimes(1);
  await act(async () => finish());
  await act(async () => { await vi.advanceTimersByTimeAsync(999); });
  expect(read).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(read).toHaveBeenCalledTimes(2);
});

it("coalesces a burst of refreshes into one follow-up read", async () => {
  let finish!: () => void;
  read.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await act(async () => root.render(<Probe />));
  let completed = false;
  await act(async () => { void refresh().then(() => { completed = true; }); void refresh(); void refresh(); });
  expect(read).toHaveBeenCalledTimes(1);
  expect(completed).toBe(false);
  await act(async () => finish());
  expect(read).toHaveBeenCalledTimes(2);
  expect(completed).toBe(true);
});

it("aborts hidden reads and resumes once without leaving background timers", async () => {
  let finish!: () => void;
  read.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await act(async () => root.render(<Probe />));
  const signal = read.mock.calls[0][0];
  await act(async () => { visibility.visible = false; visibility.listener(false); });
  expect(signal.aborted).toBe(true);
  await act(async () => { finish(); await vi.advanceTimersByTimeAsync(5000); });
  expect(read).toHaveBeenCalledTimes(1);
  await act(async () => { visibility.visible = true; visibility.listener(true); });
  expect(read).toHaveBeenCalledTimes(2);
});

it("cancels superseded queries and disabled polls", async () => {
  const finishes: (() => void)[] = [];
  read.mockImplementation(() => new Promise((resolve) => finishes.push(resolve)));
  await act(async () => root.render(<Probe />));
  const first = read.mock.calls[0][0];
  await act(async () => root.render(<Probe query="second" />));
  expect(first.aborted).toBe(true);
  expect(read).toHaveBeenCalledTimes(2);
  const second = read.mock.calls[1][0];
  await act(async () => root.render(<Probe query="second" enabled={false} />));
  expect(second.aborted).toBe(true);
  await act(async () => { finishes.forEach((finish) => finish()); await vi.advanceTimersByTimeAsync(5000); });
  expect(read).toHaveBeenCalledTimes(2);
});

it("backs off repeated failures, lets a manual retry run immediately, and resets after recovery", async () => {
  read.mockResolvedValue(false);
  await act(async () => root.render(<Probe />));
  await act(async () => { await vi.advanceTimersByTimeAsync(1999); });
  expect(read).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(read).toHaveBeenCalledTimes(2);
  await act(async () => { await vi.advanceTimersByTimeAsync(3999); });
  expect(read).toHaveBeenCalledTimes(2);
  read.mockResolvedValue(true);
  await act(async () => { await refresh(); });
  expect(read).toHaveBeenCalledTimes(3);
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(read).toHaveBeenCalledTimes(4);
});
