import { describe, expect, it } from "vitest";
import {
  distanceBetweenPoints,
  midpointBetweenPoints,
  panViewport,
  pinchViewport,
  screenToWorld,
  zoomViewportAtPoint,
  type ViewportRect,
} from "./graphViewport";

const rect: ViewportRect = { height: 600, left: 20, top: 40, width: 800 };

describe("graph viewport gestures", () => {
  it("keeps the cursor world point stable while wheel zooming", () => {
    const viewport = { scale: 1, offsetX: 120, offsetY: -60 };
    const point = { clientX: 420, clientY: 300 };
    const before = screenToWorld(point, rect, viewport);

    const zoomed = zoomViewportAtPoint(viewport, rect, point, 1.4);

    expect(screenToWorld(point, rect, zoomed)).toEqual(before);
  });

  it("pans by adding screen deltas to viewport offsets", () => {
    expect(panViewport({ scale: 1.2, offsetX: 10, offsetY: 20 }, -14, 31)).toEqual({
      scale: 1.2,
      offsetX: -4,
      offsetY: 51,
    });
  });

  it("uses pinch distance and midpoint to zoom and pan together", () => {
    const startViewport = { scale: 1, offsetX: 0, offsetY: 0 };
    const startMidpoint = { clientX: 300, clientY: 240 };
    const startWorldMidpoint = screenToWorld(startMidpoint, rect, startViewport);

    const next = pinchViewport(startViewport, startWorldMidpoint, 100, rect, { clientX: 330, clientY: 260 }, 150);

    expect(next.scale).toBe(1.5);
    expect(screenToWorld({ clientX: 330, clientY: 260 }, rect, next)).toEqual(startWorldMidpoint);
  });

  it("clamps pinch zoom to the graph scale range", () => {
    const startWorldMidpoint = screenToWorld({ clientX: 300, clientY: 240 }, rect, { scale: 1, offsetX: 0, offsetY: 0 });

    expect(pinchViewport({ scale: 2, offsetX: 0, offsetY: 0 }, startWorldMidpoint, 20, rect, { clientX: 300, clientY: 240 }, 80).scale).toBe(2.2);
    expect(pinchViewport({ scale: 0.8, offsetX: 0, offsetY: 0 }, startWorldMidpoint, 100, rect, { clientX: 300, clientY: 240 }, 20).scale).toBe(0.45);
  });

  it("computes two-pointer geometry for touch gestures", () => {
    const a = { clientX: 10, clientY: 30 };
    const b = { clientX: 70, clientY: 110 };

    expect(distanceBetweenPoints(a, b)).toBe(100);
    expect(midpointBetweenPoints(a, b)).toEqual({ clientX: 40, clientY: 70 });
  });
});
