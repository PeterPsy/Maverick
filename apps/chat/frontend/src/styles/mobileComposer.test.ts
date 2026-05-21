import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

function readStyle(filename: string) {
  return readStyleFile(resolve(currentDir, filename));
}

function readStyleFile(filePath: string, seen = new Set<string>()): string {
  if (seen.has(filePath)) {
    return "";
  }
  seen.add(filePath);
  const styles = readFileSync(filePath, "utf8");
  return styles.replace(/@import\s+"([^"]+)";/g, (_, importPath: string) => readStyleFile(resolve(dirname(filePath), importPath), seen));
}

function cssBlock(styles: string, selector: string): string {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = styles.match(new RegExp(`${escapedSelector}\\s*{([\\s\\S]*?)}`));
  return match?.[1] || "";
}

describe("mobile chat composer layout", () => {
  it("collapses the normal composer on mobile and opens it on focus", () => {
    const responsiveStyles = readStyle("responsive.css");
    const desktopComposerStyles = readStyle("composer.css");

    expect(responsiveStyles).toContain("@media (max-width: 720px)");
    expect(responsiveStyles).toContain('grid-template-areas: "tools field actions";');
    expect(responsiveStyles).toContain(".chatapp-composer:focus-within .chatapp-composer__input-shell");
    expect(responsiveStyles).not.toContain(".chatapp-composer:has(.chatapp-composer__icon-action:active)");
    expect(responsiveStyles).toContain(".chatapp-composer:has(.chatapp-composer__tool-button:active) .chatapp-composer__input-shell");
    expect(responsiveStyles).toContain(".chatapp-composer:has(.chatapp-attachment-picker__trigger:active) .chatapp-composer__input-shell");
    expect(responsiveStyles).toContain("min-height: 2.48rem;");
    expect(desktopComposerStyles).not.toContain('grid-template-areas: "tools field actions";');
  });

  it("keeps the send button as an explicit click action", () => {
    const composerSource = readFileSync(resolve(currentDir, "../components/ComposerActions.tsx"), "utf8");
    const sendButton = composerSource.match(/className="chatapp-composer__icon-action is-send"[\s\S]*?<\/button>/)?.[0] || "";

    expect(sendButton).toContain("onClick={onSubmit}");
    expect(sendButton).toContain('type="button"');
    expect(sendButton).not.toContain('type="submit"');
  });

  it("fades transcript content under installed mobile web app chrome", () => {
    const layoutStyles = readStyle("chat/layout.css");
    const responsiveStyles = readStyle("responsive.css");

    expect(layoutStyles).toContain(".chatapp-chat-main:not(.is-empty-chat)::before");
    expect(layoutStyles).toContain("var(--maverick-shell-mobile-content-top-offset, env(safe-area-inset-top, 0px)) +");
    expect(layoutStyles).toContain("2.15rem");
    expect(layoutStyles).toContain("pointer-events: none;");
    expect(layoutStyles).toContain("2.6rem");
    expect(layoutStyles).toContain("padding-bottom: max(1.15rem, env(safe-area-inset-bottom, 0px));");
    expect(responsiveStyles).toContain(
      "padding: calc(var(--maverick-shell-mobile-content-top-offset, env(safe-area-inset-top, 0px)) + 0.72rem) 0.45rem 0.85rem;",
    );
    expect(responsiveStyles).not.toContain("var(--maverick-shell-mobile-content-top-offset, 0px) + env(safe-area-inset-top, 0px)");
  });

  it("keeps sent message attachments tied to the sent message text color", () => {
    const transcriptStyles = readStyle("chat/transcript.css");

    expect(transcriptStyles).toContain(".chatapp-human-message__attachments .chatapp-attachment-card.is-readonly");
    expect(transcriptStyles).toContain("color: inherit;");
    expect(transcriptStyles).toContain(".chatapp-human-message__attachments .chatapp-attachment-card__icon");
    expect(transcriptStyles).toContain("color: currentColor;");
  });

  it("hides the normal chat transcript scrollbar without disabling scrolling", () => {
    const layoutStyles = readStyle("chat/layout.css");
    const transcriptBlock = cssBlock(layoutStyles, ".chatapp-chat-scroll__inner");

    expect(transcriptBlock).toContain("overflow-y: auto;");
    expect(transcriptBlock).toContain("scrollbar-width: none;");
    expect(transcriptBlock).toContain("-ms-overflow-style: none;");
    expect(layoutStyles).toMatch(/\.chatapp-chat-scroll__inner::-webkit-scrollbar\s*{[\s\S]*display:\s*none;/);
  });
});
