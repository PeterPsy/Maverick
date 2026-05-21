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
    const hookSource = readWidgetFile("useFloatingWindows.ts");
    const launcherSource = readWidgetFile("FloatingLauncher.tsx");
    const menuSource = readWidgetFile("FloatingThreadMenu.tsx");
    const windowSource = readWidgetFile("FloatingWindow.tsx");
    const styles = readWidgetFile("styles.css");

    expect(hookSource).toContain("isThreadUnread");
    expect(windowSource).toContain("const isActiveThreadUnread");
    expect(launcherSource).toContain('isActiveThreadUnread ? "is-unread" : ""');
    expect(menuSource).toContain('isUnread ? "is-unread" : ""');
    expect(styles).toContain(".chat-floating-thread-menu__trigger.is-unread:not(.is-busy)");
    expect(styles).toContain(".chat-floating-thread-menu__item.is-unread:not(.is-busy)");
    expect(styles).toContain(".chat-floating-widget-launcher.is-unread:not(.is-busy)");
    expect(styles.indexOf(".chat-floating-thread-menu__trigger.is-unread:not(.is-busy)")).toBeGreaterThan(
      styles.indexOf(".chat-floating-widget-launcher:hover"),
    );
    expect(styles).toContain("border-color: #fff;");
  });

  it("marks floating chats read only from explicit floating selections", () => {
    const hookSource = readWidgetFile("useFloatingWindows.ts");
    const menuSource = readWidgetFile("FloatingThreadMenu.tsx");
    const windowSource = readWidgetFile("FloatingWindow.tsx");

    expect(hookSource).toContain("markThreadReadIfNeeded");
    expect(menuSource).toContain("void onMarkThreadRead(thread);");
    expect(windowSource).toContain("void onMarkThreadRead(activeThread);");
    expect(hookSource).toMatch(/markThreadRead\s*\(thread\.thread_id\)/);
  });
});
