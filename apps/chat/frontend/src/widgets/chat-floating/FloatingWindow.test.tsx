/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../../App";
import type { ActiveAppContext } from "../../lib/activeAppContext";
import type { ChatThread } from "../../api/client";
import { FloatingWindow } from "./FloatingWindow";
import type { FloatingChatWindow } from "./floatingState";

vi.mock("../../App", async () => {
  const { useChatVisibility } = await import('../../hooks/useChatVisibility');
  return { App: vi.fn(() => <input aria-label="Fixture draft" data-visible={useChatVisibility()} defaultValue="Saved draft" />) };
});

function thread(overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    agent_label: "",
    agent_role_id: "",
    agent_type_id: "",
    archived: false,
    availability: "free",
    created_at: "2026-05-21T00:00:00Z",
    last_user_message_at: null,
    project_id: null,
    runtime_session_id: "session-1",
    source_app_id: "chat",
    system_prompt: "",
    thread_id: "thread-1",
    title: "Selected thread",
    updated_at: "2026-05-21T00:00:00Z",
    ...overrides,
  };
}

function floatingWindow(overrides: Partial<FloatingChatWindow> = {}): FloatingChatWindow {
  return {
    draftProjectId: null,
    id: "window-1",
    isCollapsed: false,
    isDraft: false,
    threadId: "thread-1",
    ...overrides,
  };
}

describe("FloatingWindow", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(() => {
    root?.unmount();
    root = null;
    container?.remove();
    container = null;
    vi.clearAllMocks();
  });

  async function renderFloatingWindow(windowItem: FloatingChatWindow, activeAppContext: ActiveAppContext | null = null, isActive = true) {
    if (!root) {
      container = document.createElement("div");
      document.body.append(container);
      root = createRoot(container);
    }
    await act(async () => {
      root?.render(
        <FloatingWindow
          activeAppContext={activeAppContext}
          isActive={isActive}
          onClose={vi.fn()}
          onCollapseChange={vi.fn()}
          onCreateDraftChat={vi.fn()}
          onDock={vi.fn()}
          onMarkThreadRead={vi.fn()}
          onRemoveThread={vi.fn()}
          onRenameThread={vi.fn()}
          onSelectThread={vi.fn()}
          runtimeThreadsError={null}
          runtimeThreadsLoaded
          threads={[thread()]}
          windowItem={windowItem}
        />,
      );
    });
    await act(async () => { await vi.dynamicImportSettled(); });
  }

  it("does not force a new chat when stale draft state still has a selected thread", async () => {
    await renderFloatingWindow(floatingWindow({ draftProjectId: "project-1", isDraft: true, threadId: "thread-1" }));

    const appProps = vi.mocked(App).mock.calls.at(-1)?.[0];

    expect(appProps).toMatchObject({
      newChatRequestId: null,
      threadId: "thread-1",
    });
    expect(appProps).not.toHaveProperty("enablePageCapture");
  });

  it('mounts only on first opening and retains the draft while collapsed reads are suspended', async () => {
    await renderFloatingWindow(floatingWindow({ isCollapsed: true }));
    expect(App).not.toHaveBeenCalled();
    await renderFloatingWindow(floatingWindow());
    const input = container!.querySelector('input')!;
    expect(input.dataset.visible).toBe('true');
    input.value = 'Unsent edit';
    await renderFloatingWindow(floatingWindow({ isCollapsed: true }));
    expect(container!.querySelector('input')).toBe(input);
    expect(input.dataset.visible).toBe('false');
    await renderFloatingWindow(floatingWindow());
    expect(container!.querySelector('input')).toBe(input);
    expect(input.value).toBe('Unsent edit');
    expect(input.dataset.visible).toBe('true');
  });
  it("pins the operational context while the shell navigates without replacing the draft", async () => {
    const storage = { app_id: "storage", name: "Storage", description: "", views: [], params: { path: "a" } };
    const crm = { app_id: "crm", name: "CRM", description: "", views: [] };
    await renderFloatingWindow(floatingWindow(), storage);
    const draft = container!.querySelector("input");
    await act(async () => container!.querySelector<HTMLButtonElement>('[aria-label="Pin app context"]')!.click());
    await renderFloatingWindow(floatingWindow(), crm);
    expect(vi.mocked(App).mock.calls.at(-1)?.[0]).toMatchObject({ activeAppContextOverride: storage });
    expect(container!.querySelector("input")).toBe(draft);
    await act(async () => container!.querySelector<HTMLButtonElement>('[aria-label="Follow app context"]')!.click());
    expect(vi.mocked(App).mock.calls.at(-1)?.[0]).toMatchObject({ activeAppContextOverride: crm });
  });

  it("defers controllers for retained windows until they become active", async () => {
    await renderFloatingWindow(floatingWindow(), null, false);
    expect(App).not.toHaveBeenCalled();
    await renderFloatingWindow(floatingWindow(), null, true);
    const input = container!.querySelector("input");
    await renderFloatingWindow(floatingWindow(), null, false);
    expect(container!.querySelector("input")).toBe(input);
    expect(input?.dataset.visible).toBe("false");
  });

  it("moves from search to a conversation with arrows and returns focus on Escape", async () => {
    await renderFloatingWindow(floatingWindow());
    const trigger = container!.querySelector<HTMLButtonElement>('[aria-label="Choose chat"]')!;
    await act(async () => trigger.click());
    const search = container!.querySelector<HTMLInputElement>('[aria-label="Search chats"]')!;
    search.focus();
    await act(async () => search.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true })));
    const selection = container!.querySelector<HTMLButtonElement>(".chat-floating-thread-menu__item-select")!;
    expect(document.activeElement).toBe(selection);
    await act(async () => selection.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(document.activeElement).toBe(trigger);
    expect(container!.querySelector('[role="dialog"]')).toBeNull();
  });

});
