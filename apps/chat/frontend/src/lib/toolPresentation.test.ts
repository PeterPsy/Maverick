import { describe, expect, it } from "vitest";
import { shellCommandActivityLabel } from "./shellCommandPresentation";
import { toolActivityLabel } from "./toolPresentation";

describe("shellCommandActivityLabel", () => {
  it("describes searches with their query and target", () => {
    expect(shellCommandActivityLabel("rg -n -S 'Tool Used' apps/chat", "started")).toBe(
      "Searching for “Tool Used” in apps/chat",
    );
    expect(shellCommandActivityLabel("rg -n -S 'Tool Used' apps/chat", "completed")).toBe(
      "Searched for “Tool Used” in apps/chat",
    );
  });

  it("distinguishes file listings from content searches", () => {
    expect(shellCommandActivityLabel("rg --files apps/chat", "completed")).toBe("Listed files in apps/chat");
    expect(shellCommandActivityLabel("ls -la apps/chat/frontend", "started")).toBe("Listing files in apps/chat/frontend");
  });

  it("extracts the file read by common shell utilities", () => {
    expect(
      shellCommandActivityLabel("sed -n '1,220p' apps/chat/frontend/src/components/ToolCallInlineMessage.tsx", "started"),
    ).toBe("Reading apps/chat/frontend/src/components/ToolCallInlineMessage.tsx");
    expect(shellCommandActivityLabel("cat apps/chat/package.json", "completed")).toBe("Read apps/chat/package.json");
  });

  it("recognizes tests, builds, type checks, lint and Git operations", () => {
    expect(shellCommandActivityLabel("npm test", "started")).toBe("Running tests");
    expect(shellCommandActivityLabel("npx vitest run apps/chat/frontend/src/lib/toolPresentation.test.ts", "completed")).toBe(
      "Ran tests for apps/chat/frontend/src/lib/toolPresentation.test.ts",
    );
    expect(shellCommandActivityLabel("npm run build", "failed")).toBe("Build failed");
    expect(shellCommandActivityLabel("tsc --noEmit", "started")).toBe("Checking types");
    expect(shellCommandActivityLabel("npm run lint", "completed")).toBe("Ran lint checks");
    expect(shellCommandActivityLabel("git status -sb", "completed")).toBe("Checked repository status");
  });

  it("unwraps shell scripts and selects the most informative compound operation", () => {
    expect(shellCommandActivityLabel('/bin/bash -lc "pwd && rg --files apps/chat"', "started")).toBe(
      "Listing files in apps/chat",
    );
    expect(shellCommandActivityLabel("pwd && npm test", "started")).toBe("Running tests");
  });

  it("uses a readable bounded fallback for unknown commands", () => {
    expect(shellCommandActivityLabel("maverick core cli list --json", "started")).toBe("Running Maverick command");
    expect(shellCommandActivityLabel("custom-check --all", "completed")).toBe("Ran custom-check");
  });
});

describe("toolActivityLabel", () => {
  it("describes web searches with their query", () => {
    expect(
      toolActivityLabel({
        detail: { query: "Maverick runtime activity", tool_kind: "web_search" },
        name: "web_search",
        status: "started",
      }),
    ).toBe("Searching the web for “Maverick runtime activity”");
    expect(
      toolActivityLabel({
        detail: { query: "Maverick runtime activity", tool_kind: "web_search" },
        name: "web_search",
        status: "completed",
      }),
    ).toBe("Searched the web for “Maverick runtime activity”");
  });

  it("uses structured file changes when available", () => {
    expect(
      toolActivityLabel({
        detail: { changes: [{ changeType: "edit", path: "apps/chat/frontend/src/App.tsx" }], tool_kind: "file_change" },
        name: "file_change",
        status: "completed",
      }),
    ).toBe("Edited apps/chat/frontend/src/App.tsx");
    expect(
      toolActivityLabel({
        detail: { changes: [{ changeType: "add", path: "one.ts" }, { changeType: "edit", path: "two.ts" }], tool_kind: "file_change" },
        name: "file_change",
        status: "started",
      }),
    ).toBe("Editing 2 files");
  });

  it("keeps hosted tool arguments private while humanizing their handle", () => {
    expect(
      toolActivityLabel({
        detail: { tool_handle: "mcp:storage_write", arguments_summary: { field_count: 2 } },
        name: "mcp:storage_write",
        status: "awaiting_confirmation",
      }),
    ).toBe("Ready to update Storage");
    expect(
      toolActivityLabel({
        detail: { tool_handle: "core-capability:filesystem.read" },
        status: "completed",
      }),
    ).toBe("Read a workspace file");
  });

  it("bounds long user-controlled fragments", () => {
    const label = toolActivityLabel({
      detail: { query: "x".repeat(200), tool_kind: "web_search" },
      name: "web_search",
      status: "started",
    });
    expect(label).toContain("…");
    expect(label.length).toBeLessThanOrEqual(112);
  });
});
