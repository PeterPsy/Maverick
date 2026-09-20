import { describe, expect, it } from "vitest";
import type { ChatThread } from "../api/client";
import {
  CHAT_THREAD_DRAG_DATA_TYPE,
  chatThreadDragPayload,
  chatThreadMentionItemsFromDataTransfer,
  chatThreadReference,
  hasChatThreadReferenceDragData,
  readChatThreadDragData,
  writeChatThreadDragData,
} from "./chatThreadDragReferences";

class FakeDataTransfer {
  effectAllowed: DataTransfer["effectAllowed"] = "uninitialized";
  types: string[] = [];
  private readonly data = new Map<string, string>();

  getData(type: string) {
    return this.data.get(type.toLowerCase()) || "";
  }

  setData(type: string, value: string) {
    const normalizedType = type.toLowerCase();
    this.data.set(normalizedType, value);
    if (!this.types.includes(normalizedType)) {
      this.types.push(normalizedType);
    }
  }
}

function thread(overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    agent_label: "Maverick",
    agent_role_id: "",
    agent_type_id: "",
    archived: false,
    availability: "free",
    created_at: "2026-09-20T08:00:00Z",
    last_completed_response_at: "2026-09-20T09:00:00Z",
    last_user_message_at: "2026-09-20T08:59:00Z",
    project_id: null,
    runtime_session_id: "session-1",
    source_app_id: "chat",
    system_prompt: "",
    thread_id: "thread-1",
    title: "Budget review",
    updated_at: "2026-09-20T09:00:00Z",
    ...overrides,
  };
}

describe("Chat thread drag references", () => {
  it("writes the sidebar thread payload and reads it as a composer reference", () => {
    const dataTransfer = new FakeDataTransfer();
    const payload = chatThreadDragPayload(thread());

    writeChatThreadDragData(dataTransfer, payload);

    expect(dataTransfer.effectAllowed).toBe("copy");
    expect(hasChatThreadReferenceDragData(dataTransfer)).toBe(true);
    expect(readChatThreadDragData(dataTransfer)).toEqual(payload);
    expect(chatThreadMentionItemsFromDataTransfer(dataTransfer)).toEqual([
      {
        id: "entity:chat:thread:thread-1",
        kind: "entity",
        label: "Budget review",
        description: "chat · thread · Chat conversation available through the authorized runtime transcript reader",
        reference: {
          type: "entity",
          app_id: "chat",
          entity_type: "thread",
          entity_id: "thread-1",
          label: "Budget review",
          summary: "Chat conversation available through the authorized runtime transcript reader",
          deep_link: "/app/chat/threads/thread-1",
        },
      },
    ]);
  });

  it("builds the same reference for runtime-thread search results", () => {
    expect(chatThreadReference(thread())).toEqual({
      type: "entity",
      app_id: "chat",
      entity_type: "thread",
      entity_id: "thread-1",
      label: "Budget review",
      summary: "Chat conversation available through the authorized runtime transcript reader",
      deep_link: "/app/chat/threads/thread-1",
    });
  });

  it("rejects spoofed owners and marker-breaking ids", () => {
    const spoofed = new FakeDataTransfer();
    spoofed.setData(CHAT_THREAD_DRAG_DATA_TYPE, JSON.stringify({
      owner_app_id: "mail",
      thread_id: "thread-1",
      title: "Spoofed",
    }));
    expect(readChatThreadDragData(spoofed)).toBeNull();

    const malformed = new FakeDataTransfer();
    malformed.setData(CHAT_THREAD_DRAG_DATA_TYPE, JSON.stringify({
      owner_app_id: "chat",
      thread_id: "thread/escape",
      title: "Malformed",
    }));
    expect(readChatThreadDragData(malformed)).toBeNull();
  });
});
