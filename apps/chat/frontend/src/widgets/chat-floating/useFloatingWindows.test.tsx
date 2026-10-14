// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deleteThread } from "../../api/client";
import type { ChatThread } from "../../api/client";
import { persistWindows, readPersistedWindows, widgetStateStorageKey } from "./floatingState";
import { useFloatingWindows } from "./useFloatingWindows";

vi.mock("../../api/client", () => ({
  deleteThread: vi.fn(), updateThread: vi.fn(), markThreadRead: vi.fn(), applyThreadCatalogPayload: vi.fn(),
}));
vi.mock("../../hooks/useRuntimeThreads", async () => {
  const { useEffect } = await import("react");
  return { useRuntimeThreads: ({ onSnapshot, setThreads }: { onSnapshot: () => void; setThreads: (threads: ChatThread[]) => void }) => {
    useEffect(() => { setThreads([{ thread_id: "thread-a" }, { thread_id: "thread-b" }] as ChatThread[]); onSnapshot(); }, []);
  } };
});
vi.mock("./floatingWidgetRuntime", async (original) => ({
  ...await original<typeof import("./floatingWidgetRuntime")>(),
  loadFloatingWidgetHostContext: async () => ({ mode: "overlay", navigationScope: "a", threadId: "", workspaceId: "default" }),
  postWidgetSize: vi.fn(),
}));

let state: ReturnType<typeof useFloatingWindows>;
function Fixture() { state = useFloatingWindows(); return null; }
const key = widgetStateStorageKey("default");
const seed = ["a", "b", "c"].map((id) => ({ id, isDraft: true, draftProjectId: `project-${id}`, threadId: "", isCollapsed: false }));

describe("contextual window ownership", () => {
  let root: Root;
  let container: HTMLDivElement;
  beforeEach(async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    localStorage.clear();
    persistWindows(key, seed);
    vi.mocked(deleteThread).mockReset();
    vi.spyOn(window, "requestAnimationFrame").mockReturnValue(0);
    container = document.createElement("div");
    root = createRoot(container);
    await act(async () => { root.render(<Fixture />); });
  });
  afterEach(() => { act(() => root.unmount()); vi.restoreAllMocks(); });

  async function context(mode: string, navigationScope = "a", threadId = "old-thread") {
    await act(async () => window.dispatchEvent(new MessageEvent("message", {
      origin: window.location.origin,
      data: { type: "maverick.widget.context-changed", owner_app_id: "chat", widget_id: "chat-floating",
        context: { content: { workspace_id: "default", payload: { mode, navigation_scope: navigationScope, thread_id: threadId } } } },
    })));
  }

  it("retains the entire stack and draft projects through docking and stale context", async () => {
    await act(async () => state.dockWindow("a"));
    await context("fixed-right");
    expect(state.windows).toEqual(seed);
    await act(async () => state.createDraftChat("a", "new-project"));
    const draft = state.windows.at(-1)!;
    await context("fixed-right");
    expect(state.hostNavigationScope).toBe(draft.id);
    expect(state.windows.at(-1)).toMatchObject({ id: draft.id, threadId: "", isDraft: true, draftProjectId: "new-project" });
    await context("mobile-fullscreen");
    await context("overlay");
    expect(readPersistedWindows(key)).toHaveLength(4);
  });

  it("close preserves each window and selecting a chat preserves the previous draft", async () => {
    await act(async () => state.closeWindow("b"));
    expect(state.windows).toHaveLength(3);
    expect(state.windows[1]).toMatchObject({ id: "b", isCollapsed: true, draftProjectId: "project-b" });
    await act(async () => state.selectThread("a", "thread-new"));
    expect(state.windows[0]).toMatchObject({ id: "a", isCollapsed: true, isDraft: true });
    expect(state.windows.at(-1)?.threadId).toBe("thread-new");
  });

  it("keeps the selected window when deleting another thread and preserves it on failure", async () => {
    await act(async () => state.selectThread("a", "thread-a"));
    const before = state.windows;
    vi.mocked(deleteThread).mockRejectedValueOnce(new Error("offline"));
    await expect(state.removeThread("a", { thread_id: "thread-a" } as ChatThread)).rejects.toThrow("offline");
    expect(state.windows).toBe(before);
    vi.mocked(deleteThread).mockResolvedValueOnce({} as Awaited<ReturnType<typeof deleteThread>>);
    await act(async () => state.removeThread("a", { thread_id: "thread-b" } as ChatThread));
    expect(state.windows).toEqual(before);
    await act(async () => state.removeThread("a", { thread_id: "thread-a" } as ChatThread));
    expect(state.windows.at(-1)).toMatchObject({ threadId: "", isDraft: true });
  });
});
