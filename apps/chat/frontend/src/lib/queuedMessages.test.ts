import { beforeEach, describe, expect, it } from "vitest";
import {
  migratePersistedQueuedMessages,
  persistQueuedMessageState,
  persistQueuedMessages,
  queueStorageKey,
  readPersistedPendingMessages,
  readPersistedQueuedMessages,
  readPersistedRecoverableQueuedMessages,
} from "./queuedMessages";

function installLocalStorageWindow() {
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        clear: () => values.clear(),
        getItem: (key: string) => values.get(key) ?? null,
        removeItem: (key: string) => {
          values.delete(key);
        },
        setItem: (key: string, value: string) => {
          values.set(key, value);
        },
      },
    },
  });
}

describe("queued message persistence", () => {
  beforeEach(() => {
    installLocalStorageWindow();
    window.localStorage.clear();
  });

  it("builds queue storage keys per navigation scope and conversation", () => {
    expect(queueStorageKey("", "draft:draft-1")).toBe("maverick.chat.queued-messages.v1:main:draft:draft-1");
    expect(queueStorageKey("widget-1", "thread:thread-1")).toBe("maverick.chat.queued-messages.v1:widget-1:thread:thread-1");
    expect(queueStorageKey("widget-1", "draft:draft-1")).not.toBe(queueStorageKey("widget-1", "draft:draft-2"));
  });

  it("persists queued messages without object URLs", () => {
    const storageKey = queueStorageKey("", "thread:thread-1");

    persistQueuedMessages(storageKey, [
      {
        clientMessageId: "message-1",
        content: "Hello",
        appReferences: [{ type: "app", app_id: "storage", label: "Storage" }],
        attachments: [
          {
            id: "attachment-1",
            name: "report.png",
            size: 123,
            type: "image/png",
            isImage: true,
            objectUrl: "blob:http://local/1",
          },
        ],
      },
    ]);

    expect(JSON.parse(window.localStorage.getItem(storageKey) || "{}").queued[0].attachments[0].objectUrl).toBeNull();
    expect(readPersistedQueuedMessages(storageKey)).toEqual([
      {
        clientMessageId: "message-1",
        content: "Hello",
        appReferences: [{ type: "app", app_id: "storage", label: "Storage" }],
        attachments: [
          {
            id: "attachment-1",
            name: "report.png",
            size: 123,
            type: "image/png",
            isImage: true,
            objectUrl: null,
          },
        ],
      },
    ]);
  });

  it("persists pending separately from queued messages", () => {
    const storageKey = queueStorageKey("", "thread:thread-1");
    const pendingMessage = {
      clientMessageId: "message-pending",
      content: "Running",
      createdAt: "2026-07-01T12:00:00.000Z",
      appReferences: [],
      attachments: [],
    };
    const queuedMessage = {
      clientMessageId: "message-queued",
      content: "Next",
      appReferences: [],
      attachments: [],
    };

    persistQueuedMessageState(storageKey, {
      pendingMessages: [pendingMessage],
      queuedMessages: [pendingMessage, queuedMessage],
    });

    expect(readPersistedPendingMessages(storageKey).map((message) => message.clientMessageId)).toEqual(["message-pending"]);
    expect(readPersistedQueuedMessages(storageKey).map((message) => message.clientMessageId)).toEqual(["message-queued"]);
    expect(readPersistedRecoverableQueuedMessages(storageKey).map((message) => message.clientMessageId)).toEqual([
      "message-pending",
      "message-queued",
    ]);
  });

  it("restores multi-agent mode for queued messages", () => {
    const storageKey = queueStorageKey("", "thread:thread-1");

    persistQueuedMessages(storageKey, [
      {
        clientMessageId: "message-1",
        content: "Review this",
        appReferences: [],
        attachments: [],
        multiAgentMode: "group_chat",
      },
    ]);

    expect(readPersistedQueuedMessages(storageKey)[0].multiAgentMode).toBe("group_chat");
  });

  it("preserves explicitly invoked skill ids across reloads", () => {
    const storageKey = queueStorageKey("", "thread:thread-1");

    persistQueuedMessages(storageKey, [
      {
        clientMessageId: "message-skill",
        content: "$storage-ops list files",
        appReferences: [],
        invokedSkillIds: ["storage-ops"],
        attachments: [],
      },
    ]);

    expect(readPersistedQueuedMessages(storageKey)[0].invokedSkillIds).toEqual(["storage-ops"]);
  });

  it("drops invalid payloads and clears empty queues", () => {
    const storageKey = queueStorageKey("", "draft:draft-1");

    window.localStorage.setItem(
      storageKey,
      JSON.stringify({
        version: 1,
        items: [{ clientMessageId: "", content: "Missing id", attachments: [] }],
      }),
    );
    expect(readPersistedQueuedMessages(storageKey)).toEqual([]);

    persistQueuedMessages(storageKey, []);
    expect(window.localStorage.getItem(storageKey)).toBeNull();
  });

  it("migrates persisted draft queues to the created thread key", () => {
    const draftStorageKey = queueStorageKey("floating-window", "draft:draft-1");
    const threadStorageKey = queueStorageKey("floating-window", "thread:thread-1");
    persistQueuedMessages(threadStorageKey, [
      {
        clientMessageId: "message-existing",
        content: "Existing queued message",
        appReferences: [],
        attachments: [],
      },
    ]);
    persistQueuedMessages(draftStorageKey, [
      {
        clientMessageId: "message-draft",
        content: "Draft queued message",
        appReferences: [],
        attachments: [],
      },
    ]);

    migratePersistedQueuedMessages("floating-window", "draft:draft-1", "thread:thread-1");

    expect(window.localStorage.getItem(draftStorageKey)).toBeNull();
    expect(readPersistedQueuedMessages(threadStorageKey).map((message) => message.clientMessageId)).toEqual(["message-existing", "message-draft"]);
  });

  it("migrates pending and queued buckets without cross-contaminating them", () => {
    const draftStorageKey = queueStorageKey("floating-window", "draft:active");
    const threadStorageKey = queueStorageKey("floating-window", "thread:thread-1");
    persistQueuedMessageState(threadStorageKey, {
      pendingMessages: [
        {
          clientMessageId: "message-existing-pending",
          content: "Existing pending",
          createdAt: "2026-07-01T12:00:00.000Z",
          appReferences: [],
          attachments: [],
        },
      ],
      queuedMessages: [{ clientMessageId: "message-existing-queued", content: "Existing queued", appReferences: [], attachments: [] }],
    });
    persistQueuedMessageState(draftStorageKey, {
      pendingMessages: [
        {
          clientMessageId: "message-draft-pending",
          content: "Draft pending",
          createdAt: "2026-07-01T12:01:00.000Z",
          appReferences: [],
          attachments: [],
        },
      ],
      queuedMessages: [{ clientMessageId: "message-draft-queued", content: "Draft queued", appReferences: [], attachments: [] }],
    });

    migratePersistedQueuedMessages("floating-window", "draft:active", "thread:thread-1");

    expect(window.localStorage.getItem(draftStorageKey)).toBeNull();
    expect(readPersistedPendingMessages(threadStorageKey).map((message) => message.clientMessageId)).toEqual([
      "message-existing-pending",
      "message-draft-pending",
    ]);
    expect(readPersistedQueuedMessages(threadStorageKey).map((message) => message.clientMessageId)).toEqual([
      "message-existing-queued",
      "message-draft-queued",
    ]);
  });
});
