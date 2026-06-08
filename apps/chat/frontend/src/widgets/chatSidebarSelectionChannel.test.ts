import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

function readWidgetSource(path: string): string {
  return readFileSync(resolve(currentDir, path), "utf8");
}

describe("chat sidebar multi-select channel", () => {
  it("uses an app-owned channel between the sidebar and footer widgets", () => {
    const channel = readWidgetSource("chatSidebarSelectionChannel.ts");
    const sidebar = readWidgetSource("chat-sidebar/useChatSidebarState.ts");
    const footer = readWidgetSource("chat-sidebar-footer/main.tsx");

    expect(channel).toContain("maverick.chat.sidebar.selection-state");
    expect(channel).toContain("BroadcastChannel");
    expect(sidebar).toContain("confirmSelectedThreadDeletion");
    expect(footer).toContain("CHAT_SIDEBAR_SELECTION_CONFIRM_DELETE");
  });

  it("renders the footer delete confirmation and storage-style trash icon", () => {
    const footer = readWidgetSource("chat-sidebar-footer/main.tsx");

    expect(footer).toContain("Delete Chat");
    expect(footer).toContain("Conferma");
    expect(footer).toContain("Annulla");
    expect(footer).toContain("M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3");
  });
});
