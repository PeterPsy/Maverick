/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatThread } from "../../api/client";
import { useThreadTouchSelection } from "./useThreadTouchSelection";

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

function pointerEvent(type: string, init: { clientX?: number; clientY?: number; pointerId?: number; pointerType?: string } = {}) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperties(event, {
    clientX: { value: init.clientX ?? 12 },
    clientY: { value: init.clientY ?? 20 },
    pointerId: { value: init.pointerId ?? 1 },
    pointerType: { value: init.pointerType ?? "touch" },
  });
  return event;
}

function TouchSelectionProbe({ isMobile = true, onSelect }: { isMobile?: boolean; onSelect: (thread: ChatThread) => void }) {
  const item = thread();
  const selection = useThreadTouchSelection({
    isShellMobileLayout: isMobile,
    selectThread: onSelect,
  });

  return (
    <button
      data-actions-revealed={selection.areThreadActionsRevealed ? "true" : "false"}
      onClick={() => selection.selectThreadFromClick(item)}
      onPointerCancel={(event) => selection.cancelThreadTouch(event, item)}
      onPointerDown={(event) => selection.trackThreadTouchStart(event, item)}
      onPointerMove={(event) => selection.trackThreadTouchMove(event, item)}
      onPointerUp={(event) => selection.selectThreadFromPointer(event, item)}
      type="button"
    >
      Budget notes
    </button>
  );
}

describe("useThreadTouchSelection", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(() => {
    root?.unmount();
    root = null;
    container?.remove();
    container = null;
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  async function renderProbe(onSelect = vi.fn()) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<TouchSelectionProbe onSelect={onSelect} />);
    });
    const button = container.querySelector("button");
    if (!button) {
      throw new Error("Expected touch selection probe button.");
    }
    return button;
  }

  it("reveals all mobile thread actions on long press without selecting the thread", async () => {
    vi.useFakeTimers();
    const onSelect = vi.fn();
    const button = await renderProbe(onSelect);

    await act(async () => {
      button.dispatchEvent(pointerEvent("pointerdown"));
    });
    await act(async () => {
      vi.advanceTimersByTime(520);
    });

    expect(button.dataset.actionsRevealed).toBe("true");

    await act(async () => {
      button.dispatchEvent(pointerEvent("pointerup"));
      button.click();
    });

    expect(onSelect).not.toHaveBeenCalled();
  });

  it("keeps ordinary mobile taps selecting the thread", async () => {
    vi.useFakeTimers();
    const onSelect = vi.fn();
    const button = await renderProbe(onSelect);

    await act(async () => {
      button.dispatchEvent(pointerEvent("pointerdown"));
      button.dispatchEvent(pointerEvent("pointerup"));
      button.click();
    });

    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});
