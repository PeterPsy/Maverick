import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

function readStyle(filename: string): string {
  return readFileSync(resolve(currentDir, filename), "utf8");
}

function cssBlock(styles: string, selector: string): string {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = styles.match(new RegExp(`${escapedSelector}\\s*{([\\s\\S]*?)}`));
  return match?.[1] || "";
}

describe("floating chat widget styles", () => {
  it("keeps overflowing floating chats recoverable with horizontal scrolling", () => {
    const styles = readStyle("styles.css");
    const stackBlock = cssBlock(styles, ".chat-floating-widget-stack");

    expect(stackBlock).toContain("width: 100%;");
    expect(stackBlock).toContain("max-width: 100%;");
    expect(stackBlock).toContain("overflow-x: auto;");
    expect(stackBlock).toContain("overflow-y: hidden;");
    expect(stackBlock).toContain("-webkit-overflow-scrolling: touch;");
    expect(stackBlock).not.toContain("overflow: hidden;");
  });
});
