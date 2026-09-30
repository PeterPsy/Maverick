import { describe, expect, it } from "vitest";
import { work } from "../testFixtures";
import {
  beforeIdForMove,
  groupByPhase,
  moveLocal,
  visibleWorks,
} from "./pipeline";

describe("pipeline", () => {
  it("computes filtered move anchors and leaves the server snapshot immutable", () => {
    const first = { ...work, id: "first", pipeline_order: 0 };
    const last = { ...work, id: "last", pipeline_order: 5 };
    const columns = groupByPhase([last, first]);
    expect(beforeIdForMove(columns, "last", "production", 0)).toBe("first");
    const moved = moveLocal(columns, "last", "approval", 0);
    expect(moved.approval[0].phase).toBe("approval");
    expect(columns.production.map((item) => item.id)).toEqual([
      "first",
      "last",
    ]);
    expect(last.phase).toBe("production");
  });
  it("supports closed work and case-insensitive partner searches", () => {
    expect(visibleWorks([work], "open", "OUTDOOR")).toHaveLength(1);
    expect(
      visibleWorks([{ ...work, phase: "completed" }], "open", ""),
    ).toHaveLength(0);
    expect(
      visibleWorks([{ ...work, phase: "completed" }], "closed", ""),
    ).toHaveLength(1);
  });
});
