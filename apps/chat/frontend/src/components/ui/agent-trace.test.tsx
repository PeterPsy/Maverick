/** @vitest-environment happy-dom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentTrace, type TraceSpan } from "./agent-trace";

let root: Root | undefined;
let host: HTMLDivElement | undefined;
beforeEach(() => { vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true); });
afterEach(() => { act(() => root?.unmount()); host?.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const spans: TraceSpan[] = [
  { id: "plan", label: "model.plan", kind: "model", start: 0, end: 1000, tokens: 100 },
  { id: "test", label: "run_tests", start: 1000, end: 2000, status: "error", detail: "2 failing" },
];
function render(props: Partial<React.ComponentProps<typeof AgentTrace>> = {}) {
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  act(() => { root!.render(<AgentTrace spans={spans} autoPlay={false} defaultTime={2000} {...props} />); });
  return host;
}
describe("AgentTrace navigation", () => {
  it("seeks with the keyboard and restores queued/running/failed states and reported tokens", () => {
    const host = render();
    const rail = host.querySelector<HTMLElement>("[role=slider]")!;
    const rows = host.querySelectorAll<HTMLElement>("[data-slot=trace-span]");
    expect(rows[1].dataset.state).toBe("error");
    act(() => rail.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true })));
    expect(rows[0].dataset.state).toBe("running");
    expect(rows[1].dataset.state).toBe("queued");
    expect(rows[0].querySelector("[data-part=meta]")?.textContent).toBe("0 tk");
    expect(rail.getAttribute("aria-valuenow")).toBe("0");
    act(() => rail.dispatchEvent(new KeyboardEvent("keydown", { key: "PageUp", bubbles: true })));
    expect(rows[0].querySelector("[data-part=meta]")?.textContent).toBe("40 tk");
    act(() => rail.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true })));
    expect(rows[1].querySelector("[data-part=status]")?.textContent).toBe("failed");
    expect(host.querySelector("[data-slot=agent-trace]")?.getAttribute("data-run")).toBe("error");
  });

  it("announces pending confirmation and calls back with the selected span", () => {
    const onSpanSelect = vi.fn();
    const host = render({ live: true, currentTime: 2000, spans: [{ ...spans[0], status: "waiting", end: 2000 }], onSpanSelect });
    expect(host.textContent).toContain("Awaiting confirmation");
    act(() => host.querySelector<HTMLButtonElement>("[data-slot=trace-span-label]")!.click());
    expect(onSpanSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "plan" }));
    expect(host.querySelector("[role=slider]")?.getAttribute("aria-valuenow")).toBe("2000");
  });

  it("replays from the graph without footer controls and rejoins streamed activity", () => {
    let nextFrame: FrameRequestCallback | undefined;
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => { nextFrame = callback; return 1; }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn(() => { nextFrame = undefined; }));
    const onSpanSelect = vi.fn();
    const host = render({ showTransport: false, replayOnSeek: true, currentTime: 2000, onSpanSelect });
    const rail = host.querySelector<HTMLElement>("[role=slider]")!;
    const trace = host.querySelector<HTMLElement>("[data-slot=agent-trace]")!;
    const rows = host.querySelectorAll<HTMLElement>("[data-slot=trace-span]");
    expect(rail.getAttribute("aria-label")).toBe("Timeline playhead");
    expect(host.querySelector("[data-slot=trace-play]")).toBeNull();

    act(() => rail.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true })));
    expect(rail.getAttribute("aria-valuenow")).toBe("0");
    expect(rows[1].dataset.state).toBe("queued");
    expect(trace.dataset.following).toBeUndefined();
    act(() => rail.dispatchEvent(new KeyboardEvent("keyup", { key: "Home", bubbles: true })));
    expect(trace.dataset.playing).toBe("true");
    act(() => nextFrame!(1000));
    act(() => nextFrame!(1100));
    expect(rows[0].querySelector("[data-part=meta]")?.textContent).toBe("10 tk");
    const beforeSelection = trace.style.getPropertyValue("--t");
    act(() => rows[1].querySelector<HTMLButtonElement>("[data-slot=trace-span-label]")!.click());
    expect(onSpanSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "test" }));
    expect(trace.style.getPropertyValue("--t")).toBe(beforeSelection);

    for (let now = 1200; now <= 3000; now += 100) act(() => nextFrame!(now));
    expect(trace.dataset.playing).toBeUndefined();
    expect(trace.dataset.following).toBe("true");
    expect(rows[1].dataset.state).toBe("error");
    act(() => root!.render(<AgentTrace spans={[...spans, { id: "next", label: "search", start: 2000, end: 2500, status: "running" }]} currentTime={2500} live autoPlay={false} showTransport={false} replayOnSeek />));
    expect(trace.style.getPropertyValue("--t")).toBe("1.00000");
    expect(host.querySelectorAll<HTMLElement>("[data-slot=trace-span]")[2].dataset.state).toBe("running");
  });

  it("pins automatic replay to the end under reduced motion", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({ matches: true, addEventListener() {}, removeEventListener() {} } as unknown as MediaQueryList);
    const host = render({ autoPlay: true, defaultTime: 0 });
    expect(host.querySelector("[role=slider]")?.getAttribute("aria-valuenow")).toBe("2000");
    expect(host.querySelector("button[aria-label='Play replay']")).not.toBeNull();
  });
});
