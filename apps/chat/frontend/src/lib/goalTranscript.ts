import type { RuntimeEvent, RuntimeStepMessage } from "../api/client";
import { runtimeStepLabel } from "./runtimeStepLabels";

export type GoalTranscriptStep = {
  cleared: boolean;
  hasDisplayState: boolean;
  hasUsage: boolean;
  status: string;
  step: RuntimeStepMessage;
};

export function goalTranscriptStep(event: RuntimeEvent): GoalTranscriptStep | null {
  if (event.event_type !== "runtime.step.updated") {
    return null;
  }
  const eventType = runtimeEventType(event.payload);
  if (!isGoalEventType(eventType)) {
    return null;
  }
  const goal = goalRecord(event.payload);
  const status = stringValue(goal.status) || stringValue(event.payload.status);
  const objective = stringValue(goal.objective) || stringValue(goal.description);
  const hasUsage = firstNumber(
    goal.tokensUsed,
    goal.tokens_used,
    goal.tokenUsage,
    goal.token_usage,
    goal.tokenBudget,
    goal.token_budget,
    goal.timeUsedSeconds,
    goal.time_used_seconds,
    goal.elapsedSeconds,
    goal.elapsed_seconds,
  ) !== undefined;

  return {
    cleared: normalizeEventType(eventType).endsWith(".cleared"),
    hasDisplayState: Boolean(status || objective),
    hasUsage,
    status,
    step: {
      label: runtimeStepLabel(event) || eventType,
      detail: event.payload,
    },
  };
}

export function goalTranscriptScope(event: RuntimeEvent): string {
  const participantId = stringValue(event.payload.inter_agent_participant_id);
  const participantBlockId = stringValue(event.payload.inter_agent_participant_block_id);
  return [event.session_id, participantId, participantBlockId].join(":");
}

export function mergeGoalTranscriptSteps(previous: RuntimeStepMessage, next: RuntimeStepMessage): RuntimeStepMessage {
  return {
    label: next.label || previous.label,
    detail: mergeRecords(previous.detail, next.detail),
  };
}

export function isTerminalGoalStatus(status: string): boolean {
  const normalized = normalizeEventType(status);
  return ["blocked", "canceled", "cancelled", "complete", "completed", "failed"].includes(normalized);
}

function runtimeEventType(detail: Record<string, unknown>): string {
  const raw = recordValue(detail.raw);
  return stringValue(detail.provider_event_type) || stringValue(raw?.type);
}

function isGoalEventType(eventType: string): boolean {
  return normalizeEventType(eventType).startsWith("thread.goal.");
}

function goalRecord(detail: Record<string, unknown>): Record<string, unknown> {
  const raw = recordValue(detail.raw);
  const item = recordValue(raw?.item);
  return recordValue(item?.goal) ?? recordValue(raw?.goal) ?? recordValue(detail.goal) ?? {};
}

function mergeRecords(previous: Record<string, unknown>, next: Record<string, unknown>): Record<string, unknown> {
  const merged = { ...previous };
  for (const [key, value] of Object.entries(next)) {
    const previousRecord = recordValue(merged[key]);
    const nextRecord = recordValue(value);
    merged[key] = previousRecord && nextRecord ? mergeRecords(previousRecord, nextRecord) : value;
  }
  return merged;
}

function normalizeEventType(value: string): string {
  return value.replace(/[\/_-]+/g, ".").replace(/\.+/g, ".").toLowerCase();
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function firstNumber(...values: unknown[]): number | undefined {
  return values.find((value): value is number => typeof value === "number" && Number.isFinite(value));
}
