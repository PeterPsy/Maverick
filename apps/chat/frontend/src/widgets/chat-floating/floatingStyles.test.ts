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
    expect(stackBlock).toContain("scrollbar-width: none;");
    expect(stackBlock).toContain("touch-action: pan-x pan-y;");
    expect(stackBlock).toContain("-webkit-overflow-scrolling: touch;");
    expect(stackBlock).not.toContain("overflow: hidden;");
    expect(styles).toMatch(/\.chat-floating-widget-stack::-webkit-scrollbar\s*{[\s\S]*display:\s*none;/);
  });

  it("lets horizontal swipes started inside an open transcript reach the floating stack", () => {
    const styles = readStyle("styles.css");
    const transcriptBlock = cssBlock(styles, ".chat-floating-widget-shell__body .chatapp-chat-scroll__inner");

    expect(transcriptBlock).toContain("overscroll-behavior-x: auto;");
    expect(transcriptBlock).toContain("overscroll-behavior-y: contain;");
    expect(transcriptBlock).toContain("scrollbar-width: none;");
    expect(transcriptBlock).toContain("-ms-overflow-style: none;");
    expect(transcriptBlock).toContain("touch-action: pan-x pan-y;");
    expect(styles).toMatch(/\.chat-floating-widget-shell__body \.chatapp-chat-scroll__inner::-webkit-scrollbar\s*{[\s\S]*display:\s*none;/);
  });

  it("hides the floating thread selector dropdown scrollbar without disabling scrolling", () => {
    const styles = readStyle("styles.css");
    const dropdownBlock = cssBlock(styles, ".chat-floating-thread-menu__panel");

    expect(dropdownBlock).toContain("max-height: min(20rem, calc(100dvh - 7rem));");
    expect(dropdownBlock).toContain("overflow-y: auto;");
    expect(dropdownBlock).toContain("scrollbar-width: none;");
    expect(dropdownBlock).toContain("-ms-overflow-style: none;");
    expect(styles).toMatch(/\.chat-floating-thread-menu__panel::-webkit-scrollbar\s*{[\s\S]*display:\s*none;/);
  });
});
