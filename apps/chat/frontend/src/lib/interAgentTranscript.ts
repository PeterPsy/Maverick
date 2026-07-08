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
  const finalSummaries: Array<{ index: number; runId: string; turnId: string }> = [];
  const agentMessages: Array<{ index: number; message: ChatMessage; turnId: string }> = [];
  const lastAgentMessageByTurnId = new Map<string, { index: number; message: ChatMessage; turnId: string }>();
  const runById = new Map(runs.map((detail) => [detail.run.run_id, detail]));

  for (const [index, message] of messages.entries()) {
    if (message.role === "step") {
      const runId = interAgentFinalSummaryRunId(message.step);
      const turnId = chatMessageTurnId(message);
      if (runId) {
        finalSummaries.push({ index, runId, turnId });
      }
    }
    if (message.role === "agent") {
      const turnId = chatMessageTurnId(message);
      const entry = { index, message, turnId };
      agentMessages.push(entry);
      if (turnId) {
        lastAgentMessageByTurnId.set(turnId, entry);
      }
    }
  }

  const linksByMessageId: Record<string, InterAgentBoardLink> = {};
  const linkedMessageIds = new Set<string>();
  const linkedRunIds = new Set<string>();

  function assignBoardLink(message: ChatMessage | null | undefined, runId: string) {
    if (!message || linkedMessageIds.has(message.id)) {
      return;
    }
    linkedMessageIds.add(message.id);
    linkedRunIds.add(runId);
    linksByMessageId[message.id] = boardLinkForRun(runId, runById, openedRunIds);
  }

  for (const summary of finalSummaries) {
    if (!summary.turnId) {
      continue;
    }
    assignBoardLink(lastAgentMessageByTurnId.get(summary.turnId)?.message, summary.runId);
  }

  for (const summary of finalSummaries) {
    if (linkedRunIds.has(summary.runId)) {
      continue;
    }
    const nextAgent = agentMessages.find((entry) => entry.index > summary.index && !linkedMessageIds.has(entry.message.id));
    const previousAgent = [...agentMessages].reverse().find((entry) => entry.index < summary.index && !linkedMessageIds.has(entry.message.id));
    const fallbackAgent = [...agentMessages].reverse().find((entry) => !linkedMessageIds.has(entry.message.id));
    assignBoardLink((nextAgent || previousAgent || fallbackAgent)?.message, summary.runId);
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
      return rootTurnIdFromProjectedParticipantTurnId(message.id.slice(0, index));
    }
  }
  return "";
}

function rootTurnIdFromProjectedParticipantTurnId(turnId: string): string {
  const marker = ":inter-agent:";
  const index = turnId.indexOf(marker);
  return index > 0 ? turnId.slice(0, index) : turnId;
}
