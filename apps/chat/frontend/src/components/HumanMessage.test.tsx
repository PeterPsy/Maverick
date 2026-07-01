/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import type { ChatMessage } from "../api/client";
import type { MentionItem } from "../lib/mentions";
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
  it("prefers entity reference markers over shorter app mention tokens", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const checklistApp: MentionItem = {
      id: "checklist",
      label: "Checklist",
      description: "Checklist app",
      kind: "app",
      reference: {
        type: "app",
        app_id: "checklist",
        label: "Checklist",
      },
    };
    const message: ChatMessage = {
      id: "msg_1",
      role: "human",
      content: "Test @Checklist drag-to-chat citations [ref:checklist/checklist/check_520a6e7a8b83]",
      createdAt: "2026-06-15T18:58:12Z",
      appReferences: [
        {
          type: "entity",
          app_id: "checklist",
          entity_type: "checklist",
          entity_id: "check_520a6e7a8b83",
          label: "Checklist drag-to-chat citations",
          summary: "4/4 checked",
          deep_link: "/app/checklist/checklists/check_520a6e7a8b83",
        },
      ],
    };

    await act(async () => {
      root?.render(<HumanMessage mentionItems={[checklistApp]} message={message} onCopyMessage={async () => true} />);
    });

    const chip = container.querySelector(".chatapp-message-reference-chip.is-entity");
    expect(chip).toBeInstanceOf(HTMLElement);
    expect(chip?.textContent).toContain("Checklist drag-to-chat citations");
    expect(container.querySelector(".chatapp-message-reference-chip.is-app")).toBeNull();
    expect(container.textContent).not.toContain("[ref:");
    expect(container.textContent?.match(/Checklist drag-to-chat citations/g)).toHaveLength(1);
  });

  it("hides entity reference markers even when app references are missing", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const message: ChatMessage = {
      id: "msg_1",
      role: "human",
      content: "Review @Old launch [ref:checklist/checklist/check_123]",
      createdAt: "2026-06-15T18:58:12Z",
      appReferences: [],
    };

    await act(async () => {
      root?.render(<HumanMessage mentionItems={[]} message={message} onCopyMessage={async () => true} />);
    });

    const chip = container.querySelector(".chatapp-message-reference-chip.is-entity");
    expect(chip).toBeInstanceOf(HTMLElement);
    expect(chip?.textContent).toContain("Old launch");
    expect(container.textContent).not.toContain("[ref:");
  });

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
        root?.render(<HumanMessage mentionItems={[]} message={message} onCopyMessage={async () => true} />);
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
