import { describe, expect, it } from "vitest";
import { openChatRootRouteInShell, openChatThreadRouteInShell } from "./shellNavigation";

function messageTarget() {
  const messages: Array<{ message: unknown; targetOrigin: string }> = [];
  return {
    messages,
    target: {
      postMessage(message: unknown, targetOrigin: string) {
        messages.push({ message, targetOrigin });
      },
    },
  };
}

describe("chat shell navigation", () => {
  it("asks the shell to expose selected chats as app page routes", () => {
    const parent = messageTarget();

    const posted = openChatThreadRouteInShell("thread-123", {
      currentWindow: {},
      origin: "https://maverick.test",
      parentWindow: parent.target,
    });

    expect(posted).toBe(true);
    expect(parent.messages).toEqual([
      {
        message: {
          type: "maverick.app.open-app",
          app_id: "chat",
          params: { app_page: "threads/thread-123" },
        },
        targetOrigin: "https://maverick.test",
      },
    ]);
  });

  it("does not change the shell route for scoped widget chat instances", () => {
    const parent = messageTarget();

    const posted = openChatThreadRouteInShell("thread-123", {
      currentWindow: {},
      navigationScope: "floating-window-1",
      origin: "https://maverick.test",
      parentWindow: parent.target,
    });

    expect(posted).toBe(false);
    expect(parent.messages).toEqual([]);
  });

  it("can ask the shell to return to the chat root", () => {
    const parent = messageTarget();

    const posted = openChatRootRouteInShell({
      currentWindow: {},
      origin: "https://maverick.test",
      parentWindow: parent.target,
    });

    expect(posted).toBe(true);
    expect(parent.messages[0]?.message).toEqual({
      type: "maverick.app.open-app",
      app_id: "chat",
      params: {},
    });
  });
});
