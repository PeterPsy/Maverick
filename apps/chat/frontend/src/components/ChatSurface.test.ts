import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

describe("ChatSurface shell workspace focus bridge", () => {
  it("requests workspace focus while the inter-agent graph is open", () => {
    const source = readFileSync(resolve(currentDir, "ChatSurface.tsx"), "utf8");

    expect(source).toContain("postShellWorkspaceFocus(isAgentNodesView)");
    expect(source).toContain("maverick.shell.workspace-focus");
    expect(source).toContain("chat.inter-agent-board");
  });
});
