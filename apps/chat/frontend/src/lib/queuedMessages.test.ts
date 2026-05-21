import { beforeEach, describe, expect, it } from "vitest";
import { persistQueuedMessages, queueStorageKey, readPersistedQueuedMessages } from "./queuedMessages";

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

  it("builds queue storage keys per navigation scope and thread", () => {
    expect(queueStorageKey("", null)).toBe("maverick.chat.queued-messages.v1:main:new");
    expect(queueStorageKey("widget-1", "thread-1")).toBe("maverick.chat.queued-messages.v1:widget-1:thread-1");
  });

  it("persists queued messages without object URLs", () => {
    const storageKey = queueStorageKey("", "thread-1");

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

    expect(JSON.parse(window.localStorage.getItem(storageKey) || "{}").items[0].attachments[0].objectUrl).toBeNull();
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

  it("drops invalid payloads and clears empty queues", () => {
    const storageKey = queueStorageKey("", null);

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
});
