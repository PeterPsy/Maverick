import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

function readWidgetFile(filename: string) {
  return readFileSync(resolve(currentDir, filename), "utf8");
}

describe("floating chat unread indicator", () => {
  it("renders unread response borders in collapsed and menu surfaces", () => {
    const source = readWidgetFile("main.tsx");
    const styles = readWidgetFile("styles.css");

    expect(source).toContain("isThreadUnread");
    expect(source).toContain("const isActiveThreadUnread");
    expect(source).toContain('isActiveThreadUnread ? "is-unread" : ""');
    expect(source).toContain('isUnread ? "is-unread" : ""');
    expect(styles).toContain(".chat-floating-thread-menu__trigger.is-unread:not(.is-busy)");
    expect(styles).toContain(".chat-floating-thread-menu__item.is-unread:not(.is-busy)");
    expect(styles).toContain(".chat-floating-widget-launcher.is-unread:not(.is-busy)");
    expect(styles.indexOf(".chat-floating-thread-menu__trigger.is-unread:not(.is-busy)")).toBeGreaterThan(
      styles.indexOf(".chat-floating-widget-launcher:hover"),
    );
    expect(styles).toContain("border-color: #fff;");
  });

  it("marks floating chats read only from explicit floating selections", () => {
    const source = readWidgetFile("main.tsx");

    expect(source).toContain("markThreadReadIfNeeded");
    expect(source).toContain("void onMarkThreadRead(thread);");
    expect(source).toContain("void onMarkThreadRead(activeThread);");
    expect(source).toMatch(/markThreadRead\s*\(thread\.thread_id\)/);
  });
});
