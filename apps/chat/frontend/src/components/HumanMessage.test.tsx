/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import type { ChatMessage } from "../api/client";
import { HumanMessage } from "./HumanMessage";

let container: HTMLDivElement | null = null;
let root: Root | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
});

describe("HumanMessage", () => {
  it("routes Storage Drive folder reference chips through shell params", async () => {
    const messages: Array<{ message: unknown; targetOrigin: string }> = [];
    const originalParent = window.parent;
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: {
        postMessage(message: unknown, targetOrigin: string) {
          messages.push({ message, targetOrigin });
        },
      },
    });

    try {
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);
      const message: ChatMessage = {
        id: "msg_1",
        role: "human",
        content: "@Reports [ref:storage/folder/drive:drive_conn_1:drive_folder_1]",
        createdAt: "2026-06-10T00:00:00Z",
        appReferences: [
          {
            type: "entity",
            app_id: "storage",
            entity_type: "folder",
            entity_id: "drive:drive_conn_1:drive_folder_1",
            label: "Reports",
            summary: "Google Drive folder",
            deep_link: "/app/storage?provider=google_drive&connection_id=drive_conn_1&drive_file_id=drive_folder_1&display_path=%2FMy+Drive%2FReports",
          },
        ],
      };

      await act(async () => {
        root?.render(<HumanMessage mentionItems={[]} message={message} onCopyMessage={async () => undefined} />);
      });

      const button = container.querySelector("button.chatapp-message-reference-chip");
      expect(button).toBeInstanceOf(HTMLButtonElement);
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

      expect(messages[0]?.message).toEqual({
        type: "maverick.app.open-app",
        app_id: "storage",
        params: {
          provider: "google_drive",
          connection_id: "drive_conn_1",
          drive_file_id: "drive_folder_1",
          display_path: "/My Drive/Reports",
        },
      });
    } finally {
      Object.defineProperty(window, "parent", { configurable: true, value: originalParent });
    }
  });
});
