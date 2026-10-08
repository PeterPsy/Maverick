/** @vitest-environment happy-dom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentTrace, type TraceSpan } from "./agent-trace";

let root: Root | undefined;
let host: HTMLDivElement | undefined;
afterEach(() => { act(() => root?.unmount()); host?.remove(); vi.restoreAllMocks(); });
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

  it("pins automatic replay to the end under reduced motion", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({ matches: true, addEventListener() {}, removeEventListener() {} } as unknown as MediaQueryList);
    const host = render({ autoPlay: true, defaultTime: 0 });
    expect(host.querySelector("[role=slider]")?.getAttribute("aria-valuenow")).toBe("2000");
    expect(host.querySelector("button[aria-label='Play replay']")).not.toBeNull();
  });
});
