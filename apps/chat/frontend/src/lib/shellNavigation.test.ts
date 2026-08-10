import { describe, expect, it } from "vitest";
import {
  chatNavigationRequestKey,
  consumeNewChatRequest,
  normalizeChatRouteParams,
  openAppParamsInShell,
  openAppRouteInShell,
  openChatRootRouteInShell,
  openChatThreadRouteInShell,
  openStoragePathInShell,
  runtimeSessionThreadMetadataFromParams,
  shellAppHrefTarget,
  shellMessageMatchesNavigationScope,
} from "./shellNavigation";

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

  it("can ask the shell to open another app page", () => {
    const parent = messageTarget();

    const posted = openAppRouteInShell("checklist", "checklists/check_123", {
      currentWindow: {},
      origin: "https://maverick.test",
      parentWindow: parent.target,
    });

    expect(posted).toBe(true);
    expect(parent.messages[0]?.message).toEqual({
      type: "maverick.app.open-app",
      app_id: "checklist",
      params: { app_page: "checklists/check_123" },
    });
  });

  it("can forward widget app-open params through the shell", () => {
    const parent = messageTarget();

    const posted = openAppParamsInShell("storage", { workspace_relative_path: "storage/generated/report.md" }, {
      currentWindow: {},
      origin: "https://maverick.test",
      parentWindow: parent.target,
    });

    expect(posted).toBe(true);
    expect(parent.messages[0]?.message).toEqual({
      type: "maverick.app.open-app",
      app_id: "storage",
      params: { workspace_relative_path: "storage/generated/report.md" },
    });
  });

  it("can ask the shell to open Storage on a workspace file path", () => {
    const parent = messageTarget();

    const posted = openStoragePathInShell("storage/generated/report.md", {
      currentWindow: {},
      origin: "https://maverick.test",
      parentWindow: parent.target,
    });

    expect(posted).toBe(true);
    expect(parent.messages[0]?.message).toEqual({
      type: "maverick.app.open-app",
      app_id: "storage",
      params: { workspace_relative_path: "storage/generated/report.md" },
    });
  });

  it("parses canonical shell app deep links into app navigation params", () => {
    expect(shellAppHrefTarget("/app/mail?thread=email_thread_123")).toEqual({
      appId: "mail",
      params: { thread: "email_thread_123" },
    });
    expect(shellAppHrefTarget("/app/checklist/checklists/check%20123?focus=details")).toEqual({
      appId: "checklist",
      params: { app_page: "checklists/check 123", focus: "details" },
    });
  });

  it("rejects links that do not belong to the canonical shell app route", () => {
    expect(shellAppHrefTarget("/apps/mail/")).toBeNull();
    expect(shellAppHrefTarget("/docs/getting-started")).toBeNull();
    expect(shellAppHrefTarget("https://example.com/app/mail?thread=thread_123")).toBeNull();
  });

  it("normalizes app_page routes into chat navigation params", () => {
    expect(normalizeChatRouteParams({ app_page: "threads/thread-123" })).toEqual({
      app_page: "threads/thread-123",
      thread_id: "thread-123",
    });
    expect(normalizeChatRouteParams({ app_page: "runtime-sessions/session-123" })).toEqual({
      app_page: "runtime-sessions/session-123",
      runtime_session_id: "session-123",
    });
    expect(normalizeChatRouteParams({ app_page: "graph/run-123" })).toEqual({
      app_page: "graph/run-123",
      view: "graph",
      inter_agent_run_id: "run-123",
    });
  });

  it("builds runtime-session thread metadata from shell params", () => {
    expect(
      runtimeSessionThreadMetadataFromParams({
        agent_label: " Researcher ",
        agent_type_id: "agent-type",
        agent_role_id: "role",
        source_app_id: "",
        thread_title: " Project notes ",
      }),
    ).toEqual({
      agent_label: "Researcher",
      agent_type_id: "agent-type",
      agent_role_id: "role",
      source_app_id: "chat",
      title: "Project notes",
    });
  });

  it("deduplicates new chat navigation requests", () => {
    const consumedRequestIds = new Set<string>();
    const consumedLegacyRequest = { current: false };

    expect(consumeNewChatRequest({ new_chat: true, new_chat_request_id: "request-1" }, consumedRequestIds, consumedLegacyRequest)).toBe(true);
    expect(consumeNewChatRequest({ new_chat: true, new_chat_request_id: "request-1" }, consumedRequestIds, consumedLegacyRequest)).toBe(false);
    expect(consumeNewChatRequest({ new_chat: true }, consumedRequestIds, consumedLegacyRequest)).toBe(true);
    expect(consumeNewChatRequest({ new_chat: true }, consumedRequestIds, consumedLegacyRequest)).toBe(false);
  });

  it("matches shell messages to the active navigation scope", () => {
    expect(shellMessageMatchesNavigationScope({}, "")).toBe(true);
    expect(shellMessageMatchesNavigationScope({ navigation_scope: "widget-1" }, "")).toBe(false);
    expect(shellMessageMatchesNavigationScope({ navigation_scope: "widget-1" }, "widget-1")).toBe(true);
    expect(shellMessageMatchesNavigationScope({ navigation_scope: "widget-2" }, "widget-1")).toBe(false);
  });

  it("creates stable navigation request keys", () => {
    expect(
      chatNavigationRequestKey({
        newChatProjectId: "project-1",
        requestedRuntimeSessionId: null,
        requestedThreadId: "thread-1",
        shouldCreateChat: true,
      }),
    ).toBe('{"new_chat":true,"project_id":"project-1","runtime_session_id":"","thread_id":"thread-1"}');
  });
});
