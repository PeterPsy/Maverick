import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

describe("chat sidebar read receipts", () => {
  it("marks a completed response read only from explicit thread selection", () => {
    const source = readFileSync(resolve(currentDir, "useChatSidebarState.ts"), "utf8");

    expect(source).toContain("void markThreadReadIfNeeded(thread);");
    expect(source).not.toContain("const activeThread = threads.find((thread) => thread.thread_id === activeThreadId)");
  });
});
