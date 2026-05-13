import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

function readStyle(filename: string) {
  return readFileSync(resolve(currentDir, filename), "utf8");
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
    const composerSource = readFileSync(resolve(currentDir, "../components/ChatComposer.tsx"), "utf8");
    const sendButton = composerSource.match(/className="chatapp-composer__icon-action is-send"[\s\S]*?<\/button>/)?.[0] || "";

    expect(sendButton).toContain("onClick={onSubmit}");
    expect(sendButton).toContain('type="button"');
    expect(sendButton).not.toContain('type="submit"');
  });

  it("fades transcript content under installed mobile web app chrome", () => {
    const layoutStyles = readStyle("chat/layout.css");
    const responsiveStyles = readStyle("responsive.css");

    expect(layoutStyles).toContain(".chatapp-chat-main:not(.is-empty-chat)::before");
    expect(layoutStyles).toContain("var(--maverick-shell-mobile-content-top-offset, 0px) +");
    expect(layoutStyles).toContain("max(2.15rem, calc(env(safe-area-inset-top, 0px) + 1.15rem))");
    expect(layoutStyles).toContain("pointer-events: none;");
    expect(layoutStyles).toContain("max(2.6rem, calc(env(safe-area-inset-top, 0px) + 0.8rem))");
    expect(layoutStyles).toContain("padding-bottom: max(1.15rem, env(safe-area-inset-bottom, 0px));");
    expect(responsiveStyles).toContain(
      "padding: calc(var(--maverick-shell-mobile-content-top-offset, 0px) + env(safe-area-inset-top, 0px) + 0.72rem) 0.45rem 0.85rem;",
    );
  });

  it("keeps sent message attachments tied to the sent message text color", () => {
    const transcriptStyles = readStyle("chat/transcript.css");

    expect(transcriptStyles).toContain(".chatapp-human-message__attachments .chatapp-attachment-card.is-readonly");
    expect(transcriptStyles).toContain("color: inherit;");
    expect(transcriptStyles).toContain(".chatapp-human-message__attachments .chatapp-attachment-card__icon");
    expect(transcriptStyles).toContain("color: currentColor;");
  });
});
