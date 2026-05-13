import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

describe("chat read receipts", () => {
  it("keeps read receipts owned by explicit sidebar selection", () => {
    const source = readFileSync(resolve(currentDir, "../App.tsx"), "utf8");
    const sidebarSource = readFileSync(resolve(currentDir, "../widgets/chat-sidebar/main.tsx"), "utf8");

    expect(source).not.toContain("markActiveThreadReadIfNeeded");
    expect(source).not.toMatch(/markThreadRead\s*\(/);
    expect(sidebarSource).toContain("void markThreadReadIfNeeded(thread);");
    expect(sidebarSource).toMatch(/markThreadRead\s*\(thread\.thread_id\)/);
  });
});
