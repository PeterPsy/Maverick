/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../../App";
import type { ChatThread } from "../../api/client";
import { FloatingWindow } from "./FloatingWindow";
import type { FloatingChatWindow } from "./floatingState";

vi.mock("../../App", () => ({
  App: vi.fn(() => null),
}));

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

  async function renderFloatingWindow(windowItem: FloatingChatWindow) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <FloatingWindow
          onClose={vi.fn()}
          onCollapseChange={vi.fn()}
          onCreateDraftChat={vi.fn()}
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
  }

  it("does not force a new chat when stale draft state still has a selected thread", async () => {
    await renderFloatingWindow(floatingWindow({ draftProjectId: "project-1", isDraft: true, threadId: "thread-1" }));

    const appProps = vi.mocked(App).mock.calls.at(-1)?.[0];

    expect(appProps).toMatchObject({
      newChatRequestId: null,
      threadId: "thread-1",
    });
  });
});
