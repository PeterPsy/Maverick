import type { ChatMessage, InterAgentRunDetail } from "../api/client";
import { isTerminalRunStatus } from "./interAgentGraph";

export type InterAgentBoardButtonState = "live" | "pending" | "normal";

export type InterAgentBoardLink = {
  runId: string;
  state: InterAgentBoardButtonState;
};

export function visiblePrimaryChatMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter((message) => !isBoardOwnedMessage(message));
}

function isBoardOwnedMessage(message: ChatMessage): boolean {
  if (message.sourceParticipantId || message.sourceRunId) {
    return true;
  }
  const detail = message.role === "step" ? message.step?.detail || {} : {};
  return detail.step_kind === "inter_agent_summary" || typeof detail.inter_agent_run_id === "string";
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
  const lastAgentMessageByTurnId = new Map<string, ChatMessage>();
  const runById = new Map(runs.map((detail) => [detail.run.run_id, detail]));

  for (const message of messages) {
    if (message.role === "agent" && !isBoardOwnedMessage(message)) {
      const turnId = chatMessageTurnId(message);
      if (turnId) {
        lastAgentMessageByTurnId.set(turnId, message);
      }
    }
  }

  const linksByMessageId: Record<string, InterAgentBoardLink> = {};
  for (const detail of runs) {
    const sourceTurnId = detail.run.source_runtime_turn_id || "";
    const message = lastAgentMessageByTurnId.get(sourceTurnId);
    if (!message) {
      continue;
    }
    linksByMessageId[message.id] = boardLinkForRun(detail.run.run_id, runById, openedRunIds);
  }

  return linksByMessageId;
}

function boardLinkForRun(
  runId: string,
  runById: ReadonlyMap<string, InterAgentRunDetail>,
  openedRunIds: ReadonlySet<string>,
): InterAgentBoardLink {
  const runDetail = runById.get(runId);
  const isTerminal = runDetail ? isTerminalRunStatus(runDetail.run.status) : true;
  return {
    runId,
    state: isTerminal ? (openedRunIds.has(runId) ? "normal" : "pending") : "live",
  };
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
