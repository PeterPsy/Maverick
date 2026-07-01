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
    expect(container.querySelector(".chatapp-inter-agent-banner")).toBeNull();
    expect(container.querySelector(".chatapp-inter-agent-message__graph")).toBeNull();

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
});

function interAgentStepMessage(): ChatMessage {
  return {
    id: "step-1",
    role: "step",
    content: "",
    createdAt: "2026-06-18T10:00:00Z",
    step: {
      label: "Orchestrator started a delegated multi-agent run.",
      detail: {
        step_kind: "inter_agent_summary",
        inter_agent_run_id: "run-1",
        summary_kind: "plan",
      },
    },
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
