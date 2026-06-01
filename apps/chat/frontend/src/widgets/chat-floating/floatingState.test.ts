import { describe, expect, it } from "vitest";
import {
  FALLBACK_WIDGET_STATE_STORAGE_KEY,
  type FloatingChatWindow,
  persistWindows,
  readPersistedOrDefaultWindows,
  readPersistedWindows,
  reconcileWindowsWithThreads,
  selectSingleFloatingWindowThread,
  widgetStateStorageKey,
} from "./floatingState";

type FakeStorage = Pick<Storage, "getItem" | "setItem">;

function windowItem(overrides: Partial<FloatingChatWindow> = {}): FloatingChatWindow {
  return {
    draftProjectId: null,
    id: "window-1",
    isCollapsed: false,
    isDraft: false,
    threadId: "thread-1",
    ...overrides,
  };
}

function fakeStorage(): FakeStorage & { entries: Map<string, string> } {
  const entries = new Map<string, string>();
  return {
    entries,
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
  };
}

describe("floating chat widget state", () => {
  it("round-trips persisted floating windows", () => {
    const storage = fakeStorage();
    const storageKey = widgetStateStorageKey("default");
    const windows = [
      windowItem({
        draftProjectId: "project-1",
        id: "window-a",
        isCollapsed: true,
        isDraft: true,
        threadId: "",
      }),
      windowItem({ id: "window-b", threadId: "thread-b" }),
    ];

    persistWindows(storageKey, windows, storage);

    expect(readPersistedWindows(storageKey, storage)).toEqual(windows);
  });

  it("hydrates workspace state before falling back to migrated global state", () => {
    const storage = fakeStorage();
    const storageKey = widgetStateStorageKey("default");
    const fallbackWindows = [windowItem({ id: "fallback", threadId: "fallback-thread" })];
    const workspaceWindows = [windowItem({ id: "workspace", threadId: "workspace-thread" })];

    persistWindows(FALLBACK_WIDGET_STATE_STORAGE_KEY, fallbackWindows, storage);
    persistWindows(storageKey, workspaceWindows, storage);

    expect(readPersistedOrDefaultWindows(storageKey, { storage })).toEqual(workspaceWindows);
  });

  it("migrates old global floating state when workspace state is absent", () => {
    const storage = fakeStorage();
    const storageKey = widgetStateStorageKey("default");
    const fallbackWindows = [windowItem({ id: "fallback", threadId: "fallback-thread" })];

    persistWindows(FALLBACK_WIDGET_STATE_STORAGE_KEY, fallbackWindows, storage);

    expect(readPersistedOrDefaultWindows(storageKey, { storage })).toEqual(fallbackWindows);
  });

  it("does not replace a missing saved thread with the first available thread", () => {
    const windows = [windowItem({ id: "window-a", threadId: "deleted-thread" })];

    expect(reconcileWindowsWithThreads(windows, [{ thread_id: "newest-thread" }])).toEqual([
      windowItem({ id: "window-a", isDraft: true, threadId: "deleted-thread" }),
    ]);
  });

  it("uses the first thread only for blank non-draft windows", () => {
    const windows = [windowItem({ id: "window-a", threadId: "" })];

    expect(reconcileWindowsWithThreads(windows, [{ thread_id: "newest-thread" }])).toEqual([
      windowItem({ id: "window-a", threadId: "newest-thread" }),
    ]);
  });

  it("clears stale draft state when the selected thread exists", () => {
    const windows = [windowItem({ id: "window-a", draftProjectId: "project-1", isDraft: true, threadId: "selected-thread" })];

    expect(reconcileWindowsWithThreads(windows, [{ thread_id: "selected-thread" }])).toEqual([
      windowItem({ id: "window-a", draftProjectId: null, isDraft: false, threadId: "selected-thread" }),
    ]);
  });

  it("updates only the scoped draft window after a chat is created", () => {
    const windows = [
      windowItem({ id: "window-a", isDraft: true, threadId: "" }),
      windowItem({ id: "window-b", isDraft: true, threadId: "" }),
    ];

    expect(reconcileWindowsWithThreads(windows, [{ thread_id: "thread-created" }], "thread-created", "window-b")).toEqual([
      windowItem({ id: "window-a", isDraft: true, threadId: "" }),
      windowItem({ id: "window-b", isDraft: false, threadId: "thread-created" }),
    ]);
  });

  it("switches the visible single-window chat in place", () => {
    const selection = selectSingleFloatingWindowThread(
      [
        windowItem({ id: "window-visible", isDraft: true, threadId: "" }),
        windowItem({ id: "window-hidden", threadId: "thread-selected" }),
      ],
      "window-visible",
      "thread-selected",
    );

    expect(selection).toEqual({
      windowId: "window-visible",
      windows: [windowItem({ id: "window-visible", isDraft: false, threadId: "thread-selected" })],
    });
  });
});
