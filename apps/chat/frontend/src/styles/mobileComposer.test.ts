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
    expect(responsiveStyles).toContain('grid-template-areas: "tools field";');
    expect(responsiveStyles).toContain(
      ".chatapp-composer:has(.chatapp-composer__editor:focus) .chatapp-composer__input-shell",
    );
    expect(responsiveStyles).not.toContain(".chatapp-composer:has(.chatapp-composer__icon-action:active)");
    expect(responsiveStyles).not.toContain(".chatapp-composer:has(.chatapp-composer__tool-button:active)");
    expect(responsiveStyles).toContain(".chatapp-composer:has(.chatapp-attachment-picker__trigger:active) .chatapp-composer__input-shell");
    expect(responsiveStyles).toContain(".chatapp-composer:has(.chatapp-provider-menu) .chatapp-composer__input-shell");
    expect(responsiveStyles).toContain("min-height: 2.48rem;");
    expect(desktopComposerStyles).not.toContain('grid-template-areas: "tools field actions";');
  });

  it("keeps the selected model label on one truncated line", () => {
    const composerStyles = readStyle("composer.css");
    const labelBlock = cssBlock(composerStyles, ".chatapp-provider-selector__label");
    const triggerBlock = cssBlock(composerStyles, ".chatapp-provider-selector__trigger");

    expect(triggerBlock).toContain("width: fit-content;");
    expect(triggerBlock).toContain("min-width: 0;");
    expect(triggerBlock).toContain("max-width: min(24rem, 48vw);");
    expect(labelBlock).toContain("overflow: hidden;");
    expect(labelBlock).toContain("text-overflow: ellipsis;");
    expect(labelBlock).toContain("white-space: nowrap;");
  });

  it("positions model and agent menus as composer-wide citation panels", () => {
    const composerStyles = readStyle("composer.css");

    expect(composerStyles).toContain(".chatapp-provider-menu,\n.chatapp-agent-menu");
    expect(composerStyles).toContain("right: 1rem;");
    expect(composerStyles).toContain("left: 1rem;");
    expect(composerStyles).toContain("bottom: calc(100% + 0.6rem);");
    expect(composerStyles).toContain("background: var(--maverick-popover-surface-strong);");
    expect(composerStyles).not.toContain("chatapp-provider-menu__header");
    expect(composerStyles).not.toContain("chatapp-agent-menu__header");
    expect(composerStyles).not.toContain("chatapp-provider-menu__search-label");
    expect(composerStyles).not.toContain("chatapp-agent-menu__search-label");
  });

  it("keeps the execution badge adjacent to the model selector", () => {
    const composerStyles = readStyle("composer.css");
    const runtimeBadgesBlock = cssBlock(composerStyles, ".chatapp-composer__runtime-badges");

    expect(runtimeBadgesBlock).toContain("flex: 0 1 auto;");
    expect(composerStyles).not.toContain("margin-left: auto;");
  });

  it("keeps the compact composer open only while voice dictation is recording", () => {
    const responsiveStyles = readStyle("responsive.css");

    expect(responsiveStyles).toContain(".chatapp-composer:has(.chatapp-composer__dictation.is-recording) .chatapp-composer__input-shell");
    expect(responsiveStyles).not.toContain(".chatapp-composer:has(.chatapp-composer__dictation.is-transcribing) .chatapp-composer__input-shell");
  });

  it("keeps the send button as an explicit click action", () => {
    const composerSource = readFileSync(resolve(currentDir, "../components/ComposerActions.tsx"), "utf8");
    const sendButton = composerSource.match(/className="chatapp-composer__icon-action is-send"[\s\S]*?<\/button>/)?.[0] || "";

    expect(sendButton).toContain("onClick={onSubmit}");
    expect(sendButton).toContain('type="button"');
    expect(sendButton).not.toContain('type="submit"');
  });

  it("shows only attachment and utility launchers until the upward mobile panel opens", () => {
    const responsiveStyles = readStyle("responsive.css");
    const utilityTriggerBlock = cssBlock(responsiveStyles, ".chatapp-composer-utilities__trigger");
    const utilityMenuBlock = cssBlock(responsiveStyles, ".chatapp-composer-utilities__menu");
    const openUtilityMenuBlock = cssBlock(responsiveStyles, ".chatapp-composer-utilities__menu.is-open");

    expect(utilityTriggerBlock).toContain("display: inline-flex;");
    expect(utilityMenuBlock).toContain("display: none;");
    expect(utilityMenuBlock).toContain("bottom: calc(100% + 0.55rem);");
    expect(openUtilityMenuBlock).toContain("display: grid;");
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
