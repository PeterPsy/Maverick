import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

function readStyle(filename: string): string {
  return readFileSync(resolve(currentDir, filename), "utf8");
}

describe("chat sidebar scroll clearance", () => {
  it("keeps the final desktop chat rows clear of the shell footer", () => {
    const styles = readStyle("styles.css");

    expect(styles).toMatch(/\.bs-widget-root\s*{[\s\S]*--chat-sidebar-scroll-under-bottom:\s*6\.8rem;/);
    expect(styles).toMatch(/\.bs-widget-root\.is-shell-mobile\s*{[\s\S]*--chat-sidebar-scroll-under-bottom:\s*3\.9rem;/);
  });
});

describe("chat sidebar search", () => {
  it("uses the compact glass search frame copied from the Skills sidebar pattern", () => {
    const styles = readStyle("styles.css");

    expect(styles).toContain("--chat-sidebar-scroll-under-top: 3.12rem;");
    expect(styles).toContain("--chat-sidebar-search-height: 2.65rem;");
    expect(styles).toContain(".bs-chat-sidebar-search-frame");
    expect(styles).toContain("grid-template-columns: auto minmax(0, 1fr);");
    expect(styles).toContain("border-radius: 22px;");
    expect(styles).toContain("backdrop-filter: blur(26px);");
    expect(styles).toContain(".bs-chat-sidebar-search-frame:focus-within");
    expect(styles).toMatch(
      /padding: calc\(var\(--chat-sidebar-(?:scroll-under-top\) \+ var\(--chat-sidebar-search-height|source-filter-top\) \+ var\(--chat-sidebar-source-filter-height)\) \+ 0\.72rem\) 0 var\(--chat-sidebar-scroll-under-bottom\);/,
    );
  });

  it("keeps the source filter buttons on blurred glass surfaces", () => {
    const styles = readStyle("styles.css");

    expect(styles).toMatch(/\.bs-chat-sidebar-source-filter\s*{[\s\S]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\);/);
    expect(styles).toMatch(/\.bs-chat-sidebar-source-filter__button\s*{[\s\S]*background:\s*var\(--chat-sidebar-glass-surface\);/);
    expect(styles).toMatch(/\.bs-chat-sidebar-source-filter__button\s*{[\s\S]*backdrop-filter:\s*blur\(26px\);/);
    expect(styles).toMatch(/\.bs-chat-sidebar-source-filter__button\s*{[\s\S]*-webkit-backdrop-filter:\s*blur\(26px\);/);
  });

  it("keeps source badges compact as icon-only pills", () => {
    const styles = readStyle("styles.css");

    expect(styles).toContain(".bs-chat-list__meta");
    expect(styles).toMatch(/\.bs-chat-list__trailing\s*{[\s\S]*width:\s*4\.85rem;/);
    expect(styles).toMatch(/\.bs-chat-list__source-badges\s*{[\s\S]*position:\s*absolute;/);
    expect(styles).toMatch(/\.bs-chat-list__source-badges\s*{[\s\S]*opacity:\s*0\.54;/);
    expect(styles).toContain("--chat-sidebar-source-badge-bg: rgba(255, 255, 255, 0.86);");
    expect(styles).toContain("--chat-sidebar-source-badge-text: #0a0a0b;");
    expect(styles).toContain("--chat-sidebar-source-badge-bg: rgba(15, 23, 42, 0.88);");
    expect(styles).toContain("--chat-sidebar-source-badge-text: #ffffff;");
    expect(styles).toMatch(/\.bs-chat-list__source-badge\s*{[\s\S]*width:\s*1\.32rem;/);
    expect(styles).toMatch(/\.bs-chat-list__source-badge\s*{[\s\S]*padding:\s*0;/);
    expect(styles).toMatch(/\.bs-chat-list__source-badge\s*{[\s\S]*background:\s*var\(--chat-sidebar-source-badge-bg\);/);
    expect(styles).toMatch(/\.bs-chat-list__source-badge\s*{[\s\S]*color:\s*var\(--chat-sidebar-source-badge-text\);/);
    expect(styles).toMatch(/\.bs-chat-list__source-badge \.material-symbols-rounded\s*{[\s\S]*color:\s*currentColor;/);
    expect(styles).toContain(".bs-chat-list__source-badges");
    expect(styles).toContain(".bs-chat-list__item:hover .bs-chat-list__source-badges");
  });
});

describe("chat sidebar unread response state", () => {
  it("renders a theme-aware accent border for completed unread responses", () => {
    const styles = readStyle("styles.css");

    expect(styles).toContain(".bs-chat-list__item.is-unread:not(.is-busy)");
    expect(styles).toContain("border-color: var(--maverick-accent);");
    expect(styles.indexOf(".bs-chat-list__item.is-unread:not(.is-busy)")).toBeGreaterThan(styles.indexOf(".bs-chat-list__item.is-expanded"));
  });
});

describe("chat sidebar project delete confirmation", () => {
  it("uses an inline confirmation surface inside the sandboxed widget", () => {
    const styles = readStyle("styles.css");

    expect(styles).toContain(".bs-chat-project-delete-confirm");
    expect(styles).toContain(".bs-chat-project-delete-confirm__actions");
    expect(styles).toContain(".bs-chat-project-delete-confirm__button.is-danger");
  });
});

describe("chat sidebar multi-select affordance", () => {
  it("keeps the circular selection control hidden until row interaction or selection", () => {
    const styles = readStyle("styles.css");

    expect(styles).toContain(".bs-chat-list__trailing");
    expect(styles).toContain(".bs-chat-list__timestamp");
    expect(styles).toContain(".bs-chat-list__selection-toggle");
    expect(styles).toContain(".bs-chat-list__selection-ring");
    expect(styles).toContain(".bs-chat-list__item.is-selected .bs-chat-list__selection-toggle");
    expect(styles).toContain(".bs-chat-list__item:hover .bs-chat-list__selection-toggle");
    expect(styles).toContain(".bs-chat-list__item:hover .bs-chat-list__meta");
    expect(styles).toContain(".bs-widget-root.has-thread-selection");
    expect(styles).toContain(".bs-widget-root.is-shell-mobile.has-thread-actions-revealed .bs-chat-list__item .bs-instance-menu__trigger");
    expect(styles).toContain(".bs-widget-root.is-shell-mobile.has-thread-actions-revealed .bs-chat-list__item .bs-chat-list__meta");
    expect(styles).toContain("--chat-sidebar-scroll-under-bottom: 9.8rem;");
  });
});
