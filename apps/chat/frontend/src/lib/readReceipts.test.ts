import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

describe("chat read receipts", () => {
  it("marks an open chat read only from explicit user interaction", () => {
    const source = readFileSync(resolve(currentDir, "../App.tsx"), "utf8");
    const hookSource = readFileSync(resolve(currentDir, "../hooks/useChatReadReceipts.ts"), "utf8");
    const sidebarSource = readFileSync(resolve(currentDir, "../widgets/chat-sidebar/main.tsx"), "utf8");

    expect(source).toContain("onPointerDown={handleChatRootPointerDown}");
    expect(hookSource).toContain("void markActiveThreadReadIfNeeded(activeThread);");
    expect(hookSource).toMatch(/markThreadRead\s*\(thread\.thread_id\)/);
    expect(source).not.toContain("isAppVisible");
    expect(source).not.toContain("maverick.app.visibility-changed");
    expect(sidebarSource).toContain("void markThreadReadIfNeeded(thread);");
    expect(sidebarSource).toMatch(/markThreadRead\s*\(thread\.thread_id\)/);
  });
});
