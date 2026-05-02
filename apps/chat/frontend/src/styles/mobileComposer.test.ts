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
    expect(responsiveStyles).toContain(".chatapp-composer:has(.chatapp-composer__icon-action:active) .chatapp-composer__input-shell");
    expect(responsiveStyles).toContain(".chatapp-composer:has(.chatapp-composer__tool-button:active) .chatapp-composer__input-shell");
    expect(responsiveStyles).toContain(".chatapp-composer:has(.chatapp-attachment-picker__trigger:active) .chatapp-composer__input-shell");
    expect(responsiveStyles).toContain("min-height: 2.48rem;");
    expect(desktopComposerStyles).not.toContain('grid-template-areas: "tools field actions";');
  });
});
