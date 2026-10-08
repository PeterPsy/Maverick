import { describe, expect, it } from "vitest";
import { toolCallsToTrace } from "./toolTrace";

const at = (seconds: number) => new Date(Date.UTC(2026, 9, 8, 10, 0, seconds)).toISOString();
describe("runtime action trace", () => {
  it("extends only active spans and freezes finished/error durations", () => {
    const tools = [
      { id: "first", name: "web_search", status: "completed" as const, startedAt: at(0), endedAt: at(2), createdAt: at(2), detail: { results: [1, 2] } },
      { id: "next", name: "shell", status: "updated" as const, startedAt: at(1), createdAt: at(3), detail: {} },
      { id: "error", name: "shell", status: "failed" as const, startedAt: at(2), endedAt: at(4), detail: { exit_code: 1 } },
    ];
    const trace = toolCallsToTrace(tools, Date.parse(at(5)));
    expect(trace.live).toBe(true);
    expect(trace.spans).toMatchObject([
      { id: "first", start: 0, end: 2000, status: "ok", detail: "2 results" },
      { id: "next", start: 1000, end: 5000, status: "running" },
      { id: "error", start: 2000, end: 4000, status: "error", detail: "Exit 1" },
    ]);
    expect(toolCallsToTrace(tools, Date.parse(at(8))).spans.map(s => s.end)).toEqual([2000, 8000, 4000]);
  });

  it("keeps missing timing at zero and uses only reported metadata", () => {
    const trace = toolCallsToTrace([
      { id: "parent", name: "tool", status: "completed", detail: { invocation_id: "p" } },
      { id: "child", name: "file_change", status: "completed", detail: { parent_invocation_id: "p", tool_kind: "file_change", cached: true, tokens: 250, attempt: 2 } },
    ], Date.parse(at(5)));
    expect(trace.live).toBe(false);
    expect(trace.spans[0]).toMatchObject({ start: 0, end: 0, tokens: undefined, attempt: undefined });
    expect(trace.spans[1]).toMatchObject({ parentId: "parent", kind: "io", status: "cached", tokens: 250, attempt: 2 });
  });

  it("retains the waiting state while confirmation is pending", () => {
    expect(toolCallsToTrace([{ name: "tool", status: "awaiting_confirmation", startedAt: at(0), detail: {} }], Date.parse(at(2))).spans[0].status).toBe("waiting");
  });
});
