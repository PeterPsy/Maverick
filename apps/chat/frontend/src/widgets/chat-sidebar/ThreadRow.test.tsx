/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatThread } from "../../api/client";
import { ThreadRow } from "./ThreadRow";

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
    title: "Budget notes",
    updated_at: "2026-05-21T00:00:00Z",
    ...overrides,
  };
}

describe("ThreadRow", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(() => {
    root?.unmount();
    root = null;
    container?.remove();
    container = null;
    vi.clearAllMocks();
  });

  async function renderThreadRow(item: ChatThread) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ThreadRow
          activeThreadId={null}
          expandedThreadId={null}
          expandedThreadTitle=""
          isSelected={false}
          onCloseExpandedThread={vi.fn()}
          onMoveThread={vi.fn()}
          onRemoveThread={vi.fn()}
          onRenameThread={vi.fn()}
          onSelectThreadClick={vi.fn()}
          onSelectThreadPointer={vi.fn()}
          onSetExpandedThreadTitle={vi.fn()}
          onToggleThreadEdit={vi.fn()}
          onToggleThreadSelection={vi.fn()}
          onTrackThreadTouchStart={vi.fn()}
          canMoveThread
          projects={[]}
          sectionProjectId={null}
          sectionTitle="No project"
          thread={item}
        />,
      );
    });
  }

  it("shows a skeleton title while thread title generation is pending", async () => {
    await renderThreadRow(thread({ title: "New chat", title_pending: true, title_source: "pending" }));

    expect(container?.querySelector(".bs-chat-list__title-skeleton")).not.toBeNull();
    expect(container?.textContent).not.toContain("New chat");
    expect(container?.querySelector<HTMLButtonElement>('button[aria-label="Edit chat"]')?.disabled).toBe(true);
  });

  it("shows the resolved title after thread title generation completes", async () => {
    await renderThreadRow(thread({ title: "Analisi Budget Vendite Mensili", title_pending: false, title_source: "ai" }));

    expect(container?.querySelector(".bs-chat-list__title-skeleton")).toBeNull();
    expect(container?.textContent).toContain("Analisi Budget Vendite Mensili");
  });
});
