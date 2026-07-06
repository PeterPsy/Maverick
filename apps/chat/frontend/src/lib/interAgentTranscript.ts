import type { ChatMessage, InterAgentRunDetail, RuntimeStepMessage } from "../api/client";
import { isTerminalRunStatus } from "./interAgentGraph";

const FINAL_INTER_AGENT_SUMMARY_KINDS = new Set(["completed", "failed", "cancelled"]);

export type InterAgentBoardButtonState = "live" | "pending" | "normal";

export type InterAgentBoardLink = {
  runId: string;
  state: InterAgentBoardButtonState;
};

export function visiblePrimaryChatMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter((message) => !isInterAgentSummaryStepMessage(message));
}

export function isInterAgentSummaryStepMessage(message: ChatMessage): boolean {
  return message.role === "step" && isInterAgentSummaryStep(message.step);
}

export function isInterAgentSummaryStep(step: RuntimeStepMessage | null | undefined): boolean {
  const detail = step?.detail || {};
  return typeof detail.step_kind === "string" && detail.step_kind === "inter_agent_summary";
}

export function interAgentFinalSummaryRunId(step: RuntimeStepMessage | null | undefined): string {
  if (!isInterAgentSummaryStep(step)) {
    return "";
  }
  const detail = step?.detail || {};
  const summaryKind = typeof detail.summary_kind === "string" ? detail.summary_kind : "";
  const runId = typeof detail.inter_agent_run_id === "string" ? detail.inter_agent_run_id.trim() : "";
  return FINAL_INTER_AGENT_SUMMARY_KINDS.has(summaryKind) ? runId : "";
}

export function interAgentBoardLinksByMessageId({
  openedRunIds,
  runs,
  messages,
}: {
  openedRunIds: ReadonlySet<string>;
  runs: InterAgentRunDetail[];
  messages: ChatMessage[];
}): Record<string, InterAgentBoardLink> {
  const finalRunIdByTurnId = new Map<string, string>();
  const lastAgentMessageByTurnId = new Map<string, ChatMessage>();
  const runById = new Map(runs.map((detail) => [detail.run.run_id, detail]));

  for (const message of messages) {
    if (message.role === "step") {
      const runId = interAgentFinalSummaryRunId(message.step);
      const turnId = chatMessageTurnId(message);
      if (runId && turnId) {
        finalRunIdByTurnId.set(turnId, runId);
      }
    }
    if (message.role === "agent") {
      const turnId = chatMessageTurnId(message);
      if (turnId) {
        lastAgentMessageByTurnId.set(turnId, message);
      }
    }
  }

  const linksByMessageId: Record<string, InterAgentBoardLink> = {};
  for (const [turnId, runId] of finalRunIdByTurnId) {
    const message = lastAgentMessageByTurnId.get(turnId);
    if (!message) {
      continue;
    }
    const runDetail = runById.get(runId);
    const isTerminal = runDetail ? isTerminalRunStatus(runDetail.run.status) : true;
    linksByMessageId[message.id] = {
      runId,
      state: isTerminal ? (openedRunIds.has(runId) ? "normal" : "pending") : "live",
    };
  }

  return linksByMessageId;
}

function chatMessageTurnId(message: ChatMessage): string {
  for (const marker of [":step:", ":agent:stream:", ":agent"]) {
    const index = message.id.indexOf(marker);
    if (index > 0) {
      return message.id.slice(0, index);
    }
  }
  return "";
}
