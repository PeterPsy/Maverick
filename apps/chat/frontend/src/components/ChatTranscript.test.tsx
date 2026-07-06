/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage, InterAgentRunDetail } from "../api/client";
import { ChatTranscript } from "./ChatTranscript";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  window.localStorage.clear();
  vi.useRealTimers();
});

describe("ChatTranscript inter-agent board entry", () => {
  it("shows the live board opener beside thinking without top inter-agent badges", async () => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    const onOpenInterAgentGraph = vi.fn();

    await act(async () => {
      root?.render(
        <ChatTranscript
          error={null}
          interAgentRuns={[runDetail("running")]}
          isLoading
          loadingLabel="Thinking"
          mentionItems={[]}
          messages={[interAgentStepMessage()]}
          onOpenInterAgentGraph={onOpenInterAgentGraph}
        />,
      );
    });

    const boardButton = container.querySelector<HTMLButtonElement>(".chatapp-pending-turn__board");
    expect(boardButton?.textContent).toContain("Open multi-agent board");
    expect(boardButton?.classList.contains("is-live")).toBe(true);
    expect(boardButton?.querySelector(".chatapp-live-board-glow")).not.toBeNull();
    expect(container.querySelector(".chatapp-inter-agent-banner")).toBeNull();
    expect(container.querySelector(".chatapp-inter-agent-message__graph")).toBeNull();
    expect(container.querySelector(".chatapp-agent-step")).toBeNull();

    await act(async () => {
      boardButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onOpenInterAgentGraph).toHaveBeenCalledWith("run-1");
  });

  it("hides the board opener once the inter-agent run is terminal", async () => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <ChatTranscript
          error={null}
          interAgentRuns={[runDetail("completed")]}
          isLoading
          loadingLabel="Thinking"
          mentionItems={[]}
          messages={[interAgentStepMessage()]}
          onOpenInterAgentGraph={vi.fn()}
        />,
      );
    });

    expect(container.querySelector(".chatapp-pending-turn__board")).toBeNull();
  });

  it("shows a pending board opener on the final assistant message until the board is opened", async () => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    const onOpenInterAgentGraph = vi.fn();

    await act(async () => {
      root?.render(
        <ChatTranscript
          error={null}
          interAgentRuns={[runDetail("completed")]}
          isLoading={false}
          loadingLabel="Thinking"
          mentionItems={[]}
          messages={[interAgentStepMessage("completed", "summary-event:step:summary-event"), agentMessage()]}
          onOpenInterAgentGraph={onOpenInterAgentGraph}
        />,
      );
    });

    expect(container.querySelector(".chatapp-agent-step")).toBeNull();
    expect(container.textContent).not.toContain("Multi-agent run completed.");
    expect(container.textContent).toContain("Final assistant answer.");

    let boardButton = container.querySelector<HTMLButtonElement>(".chatapp-agent-message-board");
    expect(boardButton?.textContent).toContain("Open multi-agent board");
    expect(boardButton?.classList.contains("is-pending")).toBe(true);
    expect(boardButton?.querySelector(".chatapp-live-board-glow")).toBeNull();

    await act(async () => {
      boardButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onOpenInterAgentGraph).toHaveBeenCalledWith("run-1");
    boardButton = container.querySelector<HTMLButtonElement>(".chatapp-agent-message-board");
    expect(boardButton?.classList.contains("is-normal")).toBe(true);
    expect(boardButton?.classList.contains("is-pending")).toBe(false);
  });
});

describe("ChatTranscript message copy", () => {
  it("shows a copied check on agent copy buttons after clipboard write succeeds", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn(async () => undefined);
    const originalClipboard = navigator.clipboard;
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    try {
      await act(async () => {
        root?.render(
          <ChatTranscript
            error={null}
            interAgentRuns={[]}
            isLoading={false}
            loadingLabel="Thinking"
            mentionItems={[]}
            messages={[message("agent-1", "agent", "Copy this answer")]}
          />,
        );
      });

      const button = container.querySelector<HTMLButtonElement>(".chatapp-message-copy-row--agent button");
      expect(button).not.toBeNull();

      await act(async () => {
        button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      });

      expect(writeText).toHaveBeenCalledWith("Copy this answer");
      expect(button?.getAttribute("aria-label")).toBe("Message copied");
      expect(button?.textContent).toContain("done");
    } finally {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: originalClipboard,
      });
    }
  });
});

function interAgentStepMessage(summaryKind = "plan", id = "turn-1:step:event-1"): ChatMessage {
  return {
    id,
    role: "step",
    content: "",
    createdAt: "2026-06-18T10:00:00Z",
    step: {
      label: summaryKind === "completed" ? "Multi-agent run completed." : "Orchestrator started a delegated multi-agent run.",
      detail: {
        step_kind: "inter_agent_summary",
        inter_agent_run_id: "run-1",
        summary_kind: summaryKind,
      },
    },
  };
}

function agentMessage(): ChatMessage {
  return {
    id: "turn-1:agent",
    role: "agent",
    content: "Final assistant answer.",
    createdAt: "2026-06-18T10:02:00Z",
    status: "complete",
  };
}

function runDetail(status: InterAgentRunDetail["run"]["status"]): InterAgentRunDetail {
  return {
    run: {
      run_id: "run-1",
      workspace_id: "default",
      thread_id: "thread-1",
      root_runtime_session_id: "session-1",
      source_app_id: "chat",
      mode: "manager_tools",
      status,
      created_by_user_id: "user:admin",
      orchestrator_participant_id: "orchestrator",
      budget_policy_id: "budget-1",
      budget_ledger_id: "ledger-1",
      visibility_level: "detail",
      created_at: "2026-06-18T10:00:00Z",
      updated_at: "2026-06-18T10:02:00Z",
      ended_at: "2026-06-18T10:02:00Z",
    },
    participants: [
      {
        participant_id: "orchestrator",
        workspace_id: "default",
        run_id: "run-1",
        kind: "orchestrator",
        execution_mode: "root_orchestrator",
        agent_type_id: null,
        label: "Orchestrator",
        runtime_session_id: null,
        status: "completed",
        current_task_id: null,
        thread_visibility: "user",
        created_at: "2026-06-18T10:00:00Z",
        updated_at: "2026-06-18T10:02:00Z",
        sequence_index: 0,
      },
    ],
    edges: [],
    budget_policy: null,
    budget_ledger: null,
  };
}

function message(id: string, role: ChatMessage["role"], content: string): ChatMessage {
  return {
    id,
    role,
    content,
    createdAt: "2026-06-18T10:00:00Z",
  };
}
