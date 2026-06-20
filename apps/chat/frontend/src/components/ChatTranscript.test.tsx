/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
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

describe("ChatTranscript inter-agent runtime steps", () => {
  it("stops pulsing older Agent nodes steps when the current run is terminal", async () => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <ChatTranscript
          error={null}
          interAgentRuns={[runDetail("completed")]}
          isLoading={false}
          loadingLabel="Loading"
          mentionItems={[]}
          messages={[interAgentStepMessage()]}
          onOpenInterAgentGraph={() => undefined}
        />,
      );
    });

    const historicalStepButton = container.querySelector(".chatapp-inter-agent-message__graph");
    expect(historicalStepButton?.classList.contains("is-live")).toBe(false);
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
