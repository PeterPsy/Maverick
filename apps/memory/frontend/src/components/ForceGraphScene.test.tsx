// @vitest-environment happy-dom
import { act, useImperativeHandle } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ForceGraphScene, { type GraphControls } from "./ForceGraphScene";

const mocks = vi.hoisted(() => ({
  props: {} as Record<string, any>, reduced: false,
  graph: {
    pauseAnimation: vi.fn(), resumeAnimation: vi.fn(), d3ReheatSimulation: vi.fn(),
    d3Force: vi.fn(), centerAt: vi.fn(), zoom: vi.fn(),
    getGraphBbox: vi.fn(() => ({ x: [-100, 100], y: [-100, 100] })),
  },
}));
vi.mock("react-force-graph-2d", () => ({ default: (props: Record<string, any>) => {
  mocks.props = props;
  useImperativeHandle(props.ref, () => mocks.graph);
  return <canvas />;
} }));

describe("force graph lifecycle", () => {
  let container: HTMLDivElement, root: Root;
  let intersect: (entries: { isIntersecting: boolean }[]) => void;
  let mediaChange: () => void;
  let controls: GraphControls | null;
  const nodes = [{ id: "a", type: "fact", title: "A" }, { id: "b", type: "fact", title: "B" }];
  const edges = [{ id: "ab", source: "a", target: "b", kind: "supports" }];
  const ready = (next: GraphControls | null) => { controls = next; };
  const select = vi.fn(), edge = vi.fn();
  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    mocks.reduced = false; controls = null;
    vi.clearAllMocks();
    mocks.graph.zoom.mockImplementation((value) => value === undefined ? 1 : mocks.graph);
    vi.stubGlobal("ResizeObserver", class {
      constructor(private callback: (entries: unknown[]) => void) {}
      observe() { this.callback([{ contentRect: { width: 1000, height: 800 } }]); }
      disconnect() {}
    });
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: typeof intersect) { intersect = callback; }
      observe() {} disconnect() {}
    });
    vi.spyOn(window, "matchMedia").mockImplementation(() => ({
      get matches() { return mocks.reduced; },
      addEventListener: (_: string, callback: () => void) => { mediaChange = callback; }, removeEventListener: vi.fn(),
    } as unknown as MediaQueryList));
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  });
  async function render(selectedId: string | null = null, motion: boolean | null = null, cards = nodes) {
    await act(async () => root.render(<ForceGraphScene nodes={cards} edges={edges} selectedId={selectedId} edgeId={null}
      motion={motion} onSelect={select} onEdge={edge} onReady={ready} />));
  }

  it("pauses offscreen animation and resumes when the graph becomes visible", async () => {
    await render();
    expect(mocks.graph.resumeAnimation).toHaveBeenCalled();
    await act(async () => intersect([{ isIntersecting: false }]));
    expect(mocks.graph.pauseAnimation).toHaveBeenCalled();
    mocks.graph.resumeAnimation.mockClear();
    await act(async () => intersect([{ isIntersecting: true }]));
    expect(mocks.graph.resumeAnimation).toHaveBeenCalledOnce();
  });

  it("freezes layout while keeping camera controls usable, then restarts physics", async () => {
    await render("a");
    expect(mocks.props.linkDirectionalParticles(mocks.props.graphData.links[0])).toBe(2);
    await render("a", false);
    expect(mocks.props.cooldownTicks).toBe(0);
    expect(mocks.props.linkDirectionalParticles(mocks.props.graphData.links[0])).toBe(0);
    controls!.zoom(1.3); expect(mocks.graph.zoom).toHaveBeenLastCalledWith(1.3, 650);
    mocks.graph.d3ReheatSimulation.mockClear();
    await render("a", true);
    expect(mocks.graph.d3ReheatSimulation).toHaveBeenCalledOnce();
  });

  it("responds to reduced motion without camera animation or flowing particles", async () => {
    await render();
    await act(async () => { mocks.reduced = true; mediaChange(); });
    expect(mocks.props.cooldownTicks).toBe(0);
    expect(mocks.props.warmupTicks).toBe(120);
    await render("a");
    expect(mocks.graph.centerAt.mock.calls.at(-1)?.[2]).toBe(0);
    expect(mocks.props.linkDirectionalParticles(mocks.props.graphData.links[0])).toBe(0);
  });

  it("allows an explicit motion choice to override the device preference for this view", async () => {
    mocks.reduced = true;
    await render("a");
    expect(mocks.props.cooldownTicks).toBe(0);
    await render("a", true);
    expect(mocks.props.cooldownTicks).toBe(Infinity);
    expect(mocks.props.warmupTicks).toBe(0);
    expect(mocks.props.linkDirectionalParticles(mocks.props.graphData.links[0])).toBe(2);
    controls!.zoom(1.3); expect(mocks.graph.zoom).toHaveBeenLastCalledWith(1.3, 650);
  });

  it("updates cards without resetting selection camera or retained simulation positions", async () => {
    await render("a");
    const node = mocks.props.graphData.nodes[0]; node.x = 123;
    mocks.graph.centerAt.mockClear();
    await render("a", true, [{ ...nodes[0], title: "Updated" }, nodes[1]]);
    expect(mocks.props.graphData.nodes[0]).toBe(node);
    expect(node.x).toBe(123);
    expect(mocks.graph.centerAt).not.toHaveBeenCalled();
    await act(async () => mocks.props.onNodeClick(node));
    expect(select).toHaveBeenLastCalledWith("a");
  });
});
