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

describe("chat sidebar unread response state", () => {
  it("renders a white border for completed unread responses", () => {
    const styles = readStyle("styles.css");

    expect(styles).toContain(".bs-chat-list__item.is-unread:not(.is-busy)");
    expect(styles).toContain("border-color: #fff;");
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
