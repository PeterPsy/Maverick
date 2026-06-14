/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  deleteThread: vi.fn(),
  getChatViewFilter: vi.fn(),
  listChatProjects: vi.fn(),
  listRuntimeSessionEvents: vi.fn(),
  markThreadRead: vi.fn(),
  setChatViewFilter: vi.fn(),
  updateThread: vi.fn(),
  useRuntimeThreads: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  deleteThread: mocks.deleteThread,
  getChatViewFilter: mocks.getChatViewFilter,
  listChatProjects: mocks.listChatProjects,
  listRuntimeSessionEvents: mocks.listRuntimeSessionEvents,
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

describe("useChatSidebarState search persistence", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mocks.listChatProjects.mockResolvedValue({ projects: [] });
    mocks.listRuntimeSessionEvents.mockResolvedValue({ items: [] });
    mocks.setChatViewFilter.mockResolvedValue({ state: { view_filter: { query: "local search" } } });
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
});
