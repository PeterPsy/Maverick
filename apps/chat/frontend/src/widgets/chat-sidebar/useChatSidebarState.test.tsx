/**
 * @vitest-environment happy-dom
 */
import { act, useEffect } from "react";
import type { Dispatch, SetStateAction } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatThread } from "../../api/client";

const mocks = vi.hoisted(() => ({
  applyThreadCatalogPayload: vi.fn((current, _payload) => current),
  deleteThread: vi.fn(),
  getChatViewFilter: vi.fn(),
  listInterAgentRuns: vi.fn(),
  listChatProjects: vi.fn(),
  listRuntimeSessionEvents: vi.fn(),
  listRuntimeThreads: vi.fn(),
  markThreadRead: vi.fn(),
  setChatViewFilter: vi.fn(),
  updateThread: vi.fn(),
  useRuntimeThreads: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  applyThreadCatalogPayload: mocks.applyThreadCatalogPayload,
  deleteThread: mocks.deleteThread,
  getChatViewFilter: mocks.getChatViewFilter,
  listInterAgentRuns: mocks.listInterAgentRuns,
  listChatProjects: mocks.listChatProjects,
  listRuntimeSessionEvents: mocks.listRuntimeSessionEvents,
  listRuntimeThreads: mocks.listRuntimeThreads,
  markThreadRead: mocks.markThreadRead,
  setChatViewFilter: mocks.setChatViewFilter,
  updateThread: mocks.updateThread,
}));

vi.mock("../../hooks/useRuntimeThreads", () => ({
  useRuntimeThreads: mocks.useRuntimeThreads,
}));

import { useChatSidebarState } from "./useChatSidebarState";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

function SidebarStateProbe() {
  const sidebar = useChatSidebarState();
  return (
    <button onClick={() => sidebar.setSearchQuery("local search")} type="button">
      {sidebar.searchQuery}
    </button>
  );
}

function SidebarSectionsProbe({ onTitles }: { onTitles: (titles: string[]) => void }) {
  const sidebar = useChatSidebarState();
  useEffect(() => {
    onTitles(sidebar.sections.flatMap((section) => section.items.map((thread) => thread.title)));
  }, [onTitles, sidebar.sections]);
  return (
    <button onClick={() => sidebar.setSearchQuery("archive")} type="button">
      Search
    </button>
  );
}

function SidebarOpenDesignFilterProbe() {
  const sidebar = useChatSidebarState();
  return (
    <button data-filter={sidebar.threadFilter} onClick={() => sidebar.setThreadFilter("opendesign")} type="button">
      {sidebar.sections.flatMap((section) => section.items.map((item) => item.title)).join(",")}
    </button>
  );
}

function SidebarHotFilterProbe() {
  const sidebar = useChatSidebarState();
  return (
    <button data-filter={sidebar.threadFilter} onClick={() => sidebar.setThreadFilter("hot")} type="button">
      {sidebar.sections.flatMap((section) => section.items.map((item) => item.title)).join(",")}
    </button>
  );
}

describe("useChatSidebarState search persistence", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mocks.listChatProjects.mockResolvedValue({ projects: [] });
    mocks.listInterAgentRuns.mockResolvedValue({ items: [] });
    mocks.listRuntimeSessionEvents.mockResolvedValue({ items: [] });
    mocks.listRuntimeThreads.mockResolvedValue({ threads: [] });
    mocks.getChatViewFilter.mockResolvedValue({ state: { view_filter: { query: "" } } });
    mocks.setChatViewFilter.mockResolvedValue({ state: { view_filter: { query: "local search" } } });
    mocks.applyThreadCatalogPayload.mockImplementation((current) => current);
    mocks.useRuntimeThreads.mockImplementation(() => undefined);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.useRealTimers();
  });

  it("does not overwrite a locally edited query when the initial view filter finishes loading", async () => {
    const viewFilter = deferred<{ state: { view_filter: { query: string } } }>();
    mocks.getChatViewFilter.mockReturnValue(viewFilter.promise);

    await act(async () => {
      root.render(<SidebarStateProbe />);
    });

    const button = container.querySelector("button");
    expect(button).not.toBeNull();

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(button?.textContent).toBe("local search");

    await act(async () => {
      viewFilter.resolve({ state: { view_filter: { query: "server search" } } });
      await viewFilter.promise;
    });
    expect(button?.textContent).toBe("local search");

    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });
    expect(mocks.setChatViewFilter).toHaveBeenCalledWith("local search");
  });

  it("backfills bounded runtime thread search results beyond the loaded page", async () => {
    const loadedThread = thread({ thread_id: "thread-loaded", runtime_session_id: "session-loaded", title: "Loaded conversation" });
    const archivedThread = thread({ thread_id: "thread-archive", runtime_session_id: "session-archive", title: "Archived incident" });
    const onTitles = vi.fn();
    mocks.applyThreadCatalogPayload.mockImplementation((current: ChatThread[], payload: { changed_thread?: ChatThread }) =>
      payload.changed_thread ? [...current.filter((item) => item.thread_id !== payload.changed_thread?.thread_id), payload.changed_thread] : current,
    );
    mocks.useRuntimeThreads.mockImplementation(({ onSnapshot, setThreads }: { onSnapshot?: (frame: { workspace_id: string }) => void; setThreads: (threads: ChatThread[]) => void }) => {
      useEffect(() => {
        setThreads([loadedThread]);
        onSnapshot?.({ workspace_id: "default" });
      }, []);
    });
    mocks.listRuntimeThreads.mockResolvedValue({ threads: [archivedThread], threads_page: { items: [archivedThread], limit: 50, has_more: false, cursor: null, sort: "recency_desc", query: "archive" } });

    await act(async () => {
      root.render(<SidebarSectionsProbe onTitles={onTitles} />);
    });
    await act(async () => {
      container.querySelector("button")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mocks.listRuntimeThreads).toHaveBeenCalledWith(expect.objectContaining({ limit: 50, query: "archive" }));
    expect(onTitles.mock.calls.some(([titles]) => titles.includes("Archived incident"))).toBe(true);
  });

  it("backfills older runtime thread pages after the bounded websocket snapshot", async () => {
    const recentThread = thread({ thread_id: "thread-recent", runtime_session_id: "session-recent", title: "Recent conversation", updated_at: "2026-07-08T00:00:00.000Z" });
    const olderThread = thread({ thread_id: "thread-older", runtime_session_id: "session-older", title: "Older conversation", created_at: "2026-06-24T00:00:00.000Z", updated_at: "2026-06-24T00:00:00.000Z" });
    const onTitles = vi.fn();
    mocks.applyThreadCatalogPayload.mockImplementation((current: ChatThread[], payload: { changed_thread?: ChatThread }) =>
      payload.changed_thread ? [...current.filter((item) => item.thread_id !== payload.changed_thread?.thread_id), payload.changed_thread] : current,
    );
    mocks.useRuntimeThreads.mockImplementation(({ onSnapshot, setThreads }: { onSnapshot?: (frame: { workspace_id: string; threads_page?: { has_more: boolean; cursor: string | null } }) => void; setThreads: (threads: ChatThread[]) => void }) => {
      useEffect(() => {
        setThreads([recentThread]);
        onSnapshot?.({
          workspace_id: "default",
          threads_page: { has_more: true, cursor: "thread-recent" },
        });
      }, []);
    });
    mocks.listRuntimeThreads.mockResolvedValue({
      threads: [olderThread],
      threads_page: { items: [olderThread], limit: 50, has_more: false, cursor: null, sort: "recency_desc", cursor_found: true },
    });

    await act(async () => {
      root.render(<SidebarSectionsProbe onTitles={onTitles} />);
    });
    await act(async () => {
      vi.advanceTimersByTime(400);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mocks.listRuntimeThreads).toHaveBeenCalledWith(expect.objectContaining({ cursor: "thread-recent", limit: 50 }));
    expect(onTitles.mock.calls.some(([titles]) => titles.includes("Older conversation"))).toBe(true);
  });

  it("accepts the OpenDesign filter and shows only Design Studio threads", async () => {
    const chatThread = thread({ thread_id: "thread-chat", runtime_session_id: "session-chat", title: "General chat" });
    const designThread = thread({
      thread_id: "thread-design",
      runtime_session_id: "session-design",
      source_app_id: "design-studio",
      title: "OpenDesign chat",
    });
    mocks.useRuntimeThreads.mockImplementation(({ setThreads }: { setThreads: (threads: ChatThread[]) => void }) => {
      useEffect(() => {
        setThreads([chatThread, designThread]);
      }, []);
    });

    await act(async () => {
      root.render(<SidebarOpenDesignFilterProbe />);
    });

    const button = container.querySelector("button");
    expect(button?.textContent).toContain("General chat");
    expect(button?.textContent).toContain("OpenDesign chat");

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(button?.dataset.filter).toBe("opendesign");
    expect(button?.textContent).toBe("OpenDesign chat");
  });

  it("anchors Hot to the newest catalog chat and shifts the window on live updates", async () => {
    const initialTime = Date.parse("2026-08-20T12:00:00.000Z");
    vi.setSystemTime(initialTime);
    const initialHotThread = thread({
      thread_id: "thread-initial-hot",
      runtime_session_id: "session-initial-hot",
      title: "Initial hot chat",
      updated_at: "2026-08-10T11:00:00.000Z",
    });
    let setLiveThreads: Dispatch<SetStateAction<ChatThread[]>> | null = null;
    mocks.useRuntimeThreads.mockImplementation(({ setThreads }: { setThreads: Dispatch<SetStateAction<ChatThread[]>> }) => {
      setLiveThreads = setThreads;
      useEffect(() => {
        setThreads([initialHotThread]);
      }, []);
    });

    await act(async () => {
      root.render(<SidebarHotFilterProbe />);
    });
    const button = container.querySelector("button");
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(button?.dataset.filter).toBe("hot");
    expect(button?.textContent).toBe("Initial hot chat");

    const liveThread = thread({
      thread_id: "thread-live-hot",
      runtime_session_id: "session-live-hot",
      title: "Live hot chat",
      availability: "active",
      updated_at: "2026-08-20T12:01:00.000Z",
    });
    vi.setSystemTime(initialTime + 1_000);
    await act(async () => {
      setLiveThreads?.((current) => [liveThread, ...current]);
    });

    expect(button?.textContent).toBe("Live hot chat");

    const completedLiveThread = {
      ...liveThread,
      availability: "free",
      has_unread_completed_response: true,
      last_completed_response_at: "2026-08-20T12:02:00.000Z",
      updated_at: "2026-08-20T12:02:00.000Z",
    };
    await act(async () => {
      setLiveThreads?.((current) => [completedLiveThread, ...current.filter((item) => item.thread_id !== liveThread.thread_id)]);
    });

    expect(button?.textContent).toBe("Live hot chat");
  });
});

function thread(overrides: Partial<ChatThread>): ChatThread {
  return {
    thread_id: "thread",
    runtime_session_id: "session",
    title: "Thread",
    agent_label: "chat",
    agent_type_id: "",
    agent_role_id: "",
    source_app_id: "chat",
    system_prompt: "",
    project_id: null,
    archived: false,
    availability: "free",
    created_at: "2026-06-29T00:00:00.000Z",
    updated_at: "2026-06-29T00:00:00.000Z",
    ...overrides,
  };
}
