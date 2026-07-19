import { describe, expect, it } from "vitest";
import type { ChatMessage, InterAgentRunDetail } from "../api/client";
import { interAgentBoardLinksByMessageId, visiblePrimaryChatMessages } from "./interAgentTranscript";

function agentMessage(id: string, content: string, extras: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id,
    role: "agent",
    content,
    createdAt: "2026-07-19T10:00:00Z",
    status: "complete",
    ...extras,
  };
}

function runDetail(status: "running" | "completed" = "running"): InterAgentRunDetail {
  return {
    run: {
      run_id: "run-1",
      workspace_id: "default",
      thread_id: "thread-1",
      root_runtime_session_id: "session-1",
      source_runtime_turn_id: "turn-1",
      source_app_id: "chat",
      mode: "orchestrated",
      orchestration_policy: "multi",
      status,
      created_by_user_id: "user-1",
      orchestrator_participant_id: "orchestrator",
      budget_policy_id: "budget-1",
      budget_ledger_id: "ledger-1",
      visibility_level: "detail",
      created_at: "2026-07-19T10:00:00Z",
      updated_at: "2026-07-19T10:00:00Z",
    },
    participants: [],
    edges: [],
    budget_policy: null,
    budget_ledger: null,
  };
}

describe("inter-agent transcript isolation", () => {
  it("keeps participant and historical board projection messages out of primary chat", () => {
    const generalist = agentMessage("turn-1:agent", "Generalist answer");
    const participant = agentMessage("child-turn:agent", "Reviewer output", {
      sourceParticipantId: "reviewer",
      sourceRunId: "run-1",
    });
    const historicalSummary: ChatMessage = {
      id: "turn-1:step:summary",
      role: "step",
      content: "Board summary",
      createdAt: "2026-07-19T10:00:01Z",
      status: "complete",
      step: { label: "Summary", detail: { step_kind: "inter_agent_summary" } },
    };

    expect(visiblePrimaryChatMessages([generalist, participant, historicalSummary])).toEqual([generalist]);
  });

  it("links the board to the independent generalist response through the source turn", () => {
    const generalist = agentMessage("turn-1:agent", "Generalist answer");
    const participant = agentMessage("turn-1:inter-agent:reviewer:agent", "Board answer", {
      sourceParticipantId: "reviewer",
      sourceRunId: "run-1",
    });

    expect(
      interAgentBoardLinksByMessageId({ messages: [generalist, participant], runs: [runDetail()], openedRunIds: new Set() }),
    ).toEqual({
      "turn-1:agent": { runId: "run-1", state: "live" },
    });
  });
});
