// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { parseLocalSnapshot, requestLocalRuntime } from "./localRuntime";

describe("local runtime protocol", () => {
  it("does not fall back to HTTP without a native host", async () => {
    expect(await requestLocalRuntime("start", "hello")).toEqual({ available: false });
  });
  it("allowlists text projection and drops raw provider material", () => {
    const result = parseLocalSnapshot({ available: true, transport: "mac-direct", phase: "ready", messages: [
      { id: "1", role: "assistant", text: "hello", imageUrl: "data:image/png;base64,private" }], auth: "secret" });
    expect(result.messages).toEqual([{ id: "1", role: "assistant", text: "hello" }]);
    expect(JSON.stringify(result)).not.toContain("secret");
    expect(JSON.stringify(result)).not.toContain("imageUrl");
  });
  it("rejects invalid roles, oversized replies and wrong transport", () => {
    const payload = { available: true, transport: "mac-direct", phase: "ready", messages: [] };
    expect(() => parseLocalSnapshot({ ...payload, transport: "ubuntu" })).toThrow();
    expect(() => parseLocalSnapshot({ ...payload, messages: [{ id: "1", role: "tool", text: "raw" }] })).toThrow();
    expect(() => parseLocalSnapshot({ ...payload, messages: [{ id: "1", role: "assistant", text: "x".repeat(64001) }] })).toThrow();
  });
});
