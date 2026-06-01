import { describe, expect, it } from "vitest";
import {
  DEFAULT_FLOATING_DOCK_NAVIGATION_SCOPE,
  floatingDockContextFromContent,
  floatingDockWindowAfterActiveThreadChanged,
  floatingDockWindowAfterWidgetMessage,
  floatingDockWindowFromContext,
} from "./floatingDockState";
import { persistWindows, readPersistedWindows, widgetStateStorageKey } from "./floatingState";

describe("floating chat dock state", () => {
  it("normalizes dock widget context into one visible dock window", () => {
    const context = floatingDockContextFromContent({
      workspace_id: " default ",
      payload: {
        navigation_scope: " window-1 ",
        mode: "fixed-right",
        thread_id: " thread-1 ",
      },
    });

    expect(context).toEqual({
      mode: "fixed-right",
      navigationScope: "window-1",
      threadId: "thread-1",
      workspaceId: "default",
    });
    expect(floatingDockWindowFromContext(context)).toEqual({
      draftProjectId: null,
      id: "window-1",
      isCollapsed: false,
      isDraft: false,
      threadId: "thread-1",
    });
  });

  it("falls back to a stable dock scope for empty context", () => {
    expect(floatingDockContextFromContent(null)).toEqual({
      mode: "fixed-right",
      navigationScope: DEFAULT_FLOATING_DOCK_NAVIGATION_SCOPE,
      threadId: "",
      workspaceId: null,
    });
  });

  it("normalizes mobile fullscreen context separately from the desktop dock", () => {
    expect(
      floatingDockContextFromContent({
        workspace_id: "default",
        payload: {
          mode: "mobile-fullscreen",
          navigation_scope: "chat-floating-mobile",
        },
      }),
    ).toEqual({
      mode: "mobile-fullscreen",
      navigationScope: "chat-floating-mobile",
      threadId: "",
      workspaceId: "default",
    });
  });

  it("hydrates an empty dock context from the newest persisted thread", () => {
    const context = floatingDockContextFromContent({
      workspace_id: "default",
      payload: {
        mode: "mobile-fullscreen",
        navigation_scope: "chat-floating-mobile",
      },
    });

    expect(
      floatingDockWindowFromContext(context, [
        {
          draftProjectId: null,
          id: "window-old",
          isCollapsed: false,
          isDraft: false,
          threadId: "thread-old",
        },
        {
          draftProjectId: null,
          id: "window-new",
          isCollapsed: false,
          isDraft: false,
          threadId: "thread-new",
        },
      ]),
    ).toEqual({
      draftProjectId: null,
      id: "chat-floating-mobile",
      isCollapsed: false,
      isDraft: false,
      threadId: "thread-new",
    });
  });

  it("preserves the active thread when a blank widget context refresh arrives", () => {
    expect(
      floatingDockWindowAfterWidgetMessage(
        {
          draftProjectId: null,
          id: "chat-floating-mobile",
          isCollapsed: false,
          isDraft: false,
          threadId: "thread-current",
        },
        {
          context: {
            content: {
              workspace_id: "default",
              payload: {
                mode: "mobile-fullscreen",
                navigation_scope: "chat-floating-mobile",
                thread_id: "",
              },
            },
          },
          owner_app_id: "chat",
          type: "maverick.widget.context-changed",
          widget_id: DEFAULT_FLOATING_DOCK_NAVIGATION_SCOPE,
        },
      ),
    ).toEqual({
      draftProjectId: null,
      id: "chat-floating-mobile",
      isCollapsed: false,
      isDraft: false,
      threadId: "thread-current",
    });
  });

  it("keeps a dock-created draft tied to the created thread before returning to overlay", () => {
    const draftWindow = floatingDockWindowFromContext({
      mode: "fixed-right",
      navigationScope: "dock-draft",
      threadId: "",
      workspaceId: "default",
    });

    const updatedWindow = floatingDockWindowAfterActiveThreadChanged(draftWindow, {
      active_thread_id: " created-thread ",
      navigation_scope: "dock-draft",
      owner_app_id: "chat",
      type: "maverick.chat.active-thread-changed",
    });

    expect(updatedWindow).toEqual({
      draftProjectId: null,
      id: "dock-draft",
      isCollapsed: false,
      isDraft: false,
      threadId: "created-thread",
    });

    const entries = new Map<string, string>();
    const storage = {
      getItem: (key: string) => entries.get(key) ?? null,
      setItem: (key: string, value: string) => entries.set(key, value),
    };
    const storageKey = widgetStateStorageKey("default");

    persistWindows(storageKey, [{ ...updatedWindow, isCollapsed: true }], storage);

    expect(readPersistedWindows(storageKey, storage)).toEqual([{ ...updatedWindow, isCollapsed: true }]);
  });

  it("accepts forwarded active-thread messages without a widget id", () => {
    const draftWindow = floatingDockWindowFromContext({
      mode: "fixed-right",
      navigationScope: "dock-draft",
      threadId: "",
      workspaceId: "default",
    });

    expect(
      floatingDockWindowAfterWidgetMessage(draftWindow, {
        active_thread_id: "created-thread",
        navigation_scope: "dock-draft",
        owner_app_id: "chat",
        type: "maverick.chat.active-thread-changed",
      }),
    ).toEqual({
      draftProjectId: null,
      id: "dock-draft",
      isCollapsed: false,
      isDraft: false,
      threadId: "created-thread",
    });
  });

  it("ignores active-thread messages for other navigation scopes", () => {
    const draftWindow = floatingDockWindowFromContext({
      mode: "fixed-right",
      navigationScope: "dock-draft",
      threadId: "",
      workspaceId: "default",
    });

    expect(
      floatingDockWindowAfterActiveThreadChanged(draftWindow, {
        active_thread_id: "created-thread",
        navigation_scope: "other-window",
        owner_app_id: "chat",
        type: "maverick.chat.active-thread-changed",
      }),
    ).toBe(draftWindow);
  });
});
