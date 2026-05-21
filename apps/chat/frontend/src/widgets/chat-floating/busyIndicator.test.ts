import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

function readWidgetFile(filename: string) {
  return readFileSync(resolve(currentDir, filename), "utf8");
}

describe("floating chat busy indicator", () => {
  it("does not publish local availability changes from the chat app", () => {
    const source = readFileSync(resolve(currentDir, "../../App.tsx"), "utf8");

    expect(source).not.toContain("activeTurnThreadAvailability");
    expect(source).not.toContain('type: "maverick.chat.thread-availability-changed"');
  });

  it("marks the collapsed launcher busy when its active thread is running", () => {
    const hookSource = readWidgetFile("useFloatingWindows.ts");
    const windowSource = readWidgetFile("FloatingWindow.tsx");
    const launcherSource = readWidgetFile("FloatingLauncher.tsx");

    expect(hookSource).toContain("useRuntimeThreads");
    expect(windowSource).toContain("const isActiveThreadBusy");
    expect(launcherSource).toContain("aria-busy={isActiveThreadBusy || undefined}");
    expect(launcherSource).toContain('isActiveThreadBusy ? "is-busy" : ""');
    expect(launcherSource).toContain("isActiveThreadBusy ? <BusyChatGlow /> : null");
    expect(hookSource).not.toContain('payload.type === "maverick.chat.thread-availability-changed"');
  });

  it("keeps the last floating window available when close is pressed", () => {
    const source = readWidgetFile("useFloatingWindows.ts");

    expect(source).toContain("if (current.length <= 1)");
    expect(source).toContain("? { ...windowItem, isCollapsed: true } : windowItem");
    expect(source).toContain("return current.filter((windowItem) => windowItem.id !== windowId);");
  });

  it("round-trips persisted draft window state", () => {
    const source = readWidgetFile("floatingState.ts");

    expect(source).toContain("draftProjectId: typeof windowItem.draftProjectId");
    expect(source).toContain("isDraft: windowItem.isDraft === true");
  });

  it("keeps the intended border glow available for collapsed and menu states", () => {
    const floatingStyles = readWidgetFile("styles.css");
    const sidebarStyles = readFileSync(resolve(currentDir, "../chat-sidebar/styles.css"), "utf8");

    expect(floatingStyles).toContain(".chat-floating-widget-launcher.is-busy");
    expect(floatingStyles).toContain(".bs-chat-list__glow-layer::before");
    expect(sidebarStyles).toContain(".bs-chat-list__glow-layer::before");
  });

  it("keeps the floating composer collapsed until it has focus or active content", () => {
    const floatingStyles = readWidgetFile("styles.css");

    expect(floatingStyles).toContain('grid-template-areas: "tools field actions";');
    expect(floatingStyles).toContain("min-height: 2.48rem;");
    expect(floatingStyles).toContain(".chatapp-composer:has(.chatapp-composer__editor:focus) .chatapp-composer__input-shell");
    expect(floatingStyles).toContain("grid-template-areas:\n    \"field\"\n    \"toolbar\";");
  });
});
