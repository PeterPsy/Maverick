import type { ChatMessage, RuntimeEvent, RuntimeStepMessage, StructuredContent, ToolCallMessage } from "../api/client";
import type { ChatMessageAttachment } from "../api/client";
import { structuredContentFromAgentLinks } from "./linkPreviews";
import { runtimeStepLabel } from "./runtimeStepLabels";

function textPayload(event: RuntimeEvent): string {
  const value = event.payload.text;
  return typeof value === "string" ? value.trim() : "";
}

function deltaTextPayload(event: RuntimeEvent): string {
  const value = event.payload.text;
  return typeof value === "string" ? value : "";
}

function structuredPayload(value: unknown): StructuredContent | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const kind = typeof record.kind === "string" ? record.kind : "";
  if (!kind) {
    return null;
  }
  const payload = record.payload && typeof record.payload === "object" ? (record.payload as Record<string, unknown>) : record;
  return { kind, payload };
}

function toolCallPayload(event: RuntimeEvent): ToolCallMessage | null {
  if (!event.event_type.startsWith("runtime.tool_call.")) {
    return null;
  }
  const status = event.event_type.split(".").at(-1);
  if (status !== "started" && status !== "updated" && status !== "completed" && status !== "failed") {
    return null;
  }
  const name = event.payload.name || event.payload.tool_name || event.payload.tool;
  return {
    id: event.event_id,
    name: typeof name === "string" && name ? name : "tool",
    status,
    detail: event.payload,
    createdAt: event.created_at,
  };
}

function normalizedRuntimeLabel(value: string): string {
  return value
    .replace(/\u001b\[[0-9;]*m/g, "")
    .replace(/\u2026/g, "...")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function skillChangeToolCallPayload(event: RuntimeEvent): ToolCallMessage | null {
  if (event.event_type !== "runtime.step.updated") {
    return null;
  }
  const label = String(event.payload.label || event.payload.message || event.payload.provider_event_type || "");
  if (normalizedRuntimeLabel(label) !== "skills changed") {
    return null;
  }
  return {
    id: event.event_id,
    name: "skills",
    status: "completed",
    detail: {
      ...event.payload,
      name: "skills",
      tool_kind: "skill_change",
      status: "completed",
      summary: "Skills changed",
    },
    createdAt: event.created_at,
  };
}

function toolCallKey(toolCall: ToolCallMessage): string {
  for (const key of ["tool_call_id", "call_id", "item_id"]) {
    const value = toolCall.detail[key];
    if (typeof value === "string" && value.trim()) {
      return `${key}:${value.trim()}`;
    }
  }
  return `event:${toolCall.id}`;
}

function mergeToolCall(previous: ToolCallMessage, next: ToolCallMessage): ToolCallMessage {
  const statusRank: Record<ToolCallMessage["status"], number> = {
    started: 1,
    updated: 2,
    completed: 3,
    failed: 4,
  };
  const selected = statusRank[next.status] >= statusRank[previous.status] ? next : previous;
  return {
    ...previous,
    ...selected,
    detail: { ...previous.detail, ...next.detail },
    createdAt: selected.createdAt || previous.createdAt,
  };
}

function stepPayload(event: RuntimeEvent): RuntimeStepMessage | null {
  const label = runtimeStepLabel(event);
  if (!label) {
    return null;
  }
  return {
    label,
    detail: event.payload,
  };
}

function readableSystemText(value: unknown, fallback: string): string {
  const text = String(value || fallback).trim();
  return text.replace(/_/g, " ");
}

export function eventsToMessages(events: RuntimeEvent[]): ChatMessage[] {
  const orderedMessages: Array<{ order: number; sequence: number; message: ChatMessage }> = [];
  let messageSequence = 0;
  const seenUserTurns = new Set<string>();
  const finalTurnIds = new Set(events.filter((event) => event.event_type === "runtime.output.final").map((event) => event.turn_id || event.event_id));
  const outputSegmentsByTurn = new Map<string, { text: string; createdAt: string; index: number; order: number }>();
  const nextOutputSegmentIndexByTurn = new Map<string, number>();
  const renderedOutputByTurn = new Map<string, string>();
  const toolSegmentsByTurn = new Map<string, { createdAt: string; itemsByKey: Map<string, ToolCallMessage>; index: number; order: number }>();
  const nextToolSegmentIndexByTurn = new Map<string, number>();

  function pushMessage(message: ChatMessage, order: number) {
    orderedMessages.push({ order, sequence: messageSequence, message });
    messageSequence += 1;
  }

  function appendRenderedOutput(turnId: string, text: string) {
    if (text) {
      renderedOutputByTurn.set(turnId, `${renderedOutputByTurn.get(turnId) || ""}${text}`);
    }
  }

  function flushOutputSegment(turnId: string, closeActive = false) {
    const segment = outputSegmentsByTurn.get(turnId);
    if (!segment || !segment.text) {
      return;
    }
    pushMessage({
      id: `${turnId}:agent:stream:${segment.index}`,
      role: "agent",
      content: segment.text,
      createdAt: segment.createdAt,
      status: closeActive ? "complete" : "pending",
    }, segment.order);
    appendRenderedOutput(turnId, segment.text);
    outputSegmentsByTurn.delete(turnId);
  }

  function flushToolSegment(turnId: string, closeActive = false) {
    const segment = toolSegmentsByTurn.get(turnId);
    if (!segment) {
      return;
    }
    const items = [...segment.itemsByKey.values()].map((item) =>
      closeActive && (item.status === "started" || item.status === "updated") ? { ...item, status: "completed" as const } : item,
    );
    if (items.length) {
      const hasFailedTool = items.some((item) => item.status === "failed");
      pushMessage({
        id: `${turnId}:tools:${segment.index}`,
        role: "tool",
        content: "Tool Used",
        createdAt: segment.createdAt,
        status: hasFailedTool ? "failed" : "complete",
        toolCalls: items,
        toolCall: items[0],
      }, segment.order);
    }
    toolSegmentsByTurn.delete(turnId);
  }

  for (const [eventIndex, event] of events.entries()) {
    const turnId = event.turn_id || event.event_id;
    if (event.event_type === "runtime.turn.queued" && !seenUserTurns.has(turnId)) {
      const input = event.payload.input_text;
      const clientMessageId = event.payload.client_message_id;
      const attachments = Array.isArray(event.payload.attachments)
        ? (event.payload.attachments.filter((item) => item && typeof item === "object") as ChatMessageAttachment[])
        : [];
      if (typeof input === "string" && input.trim()) {
        seenUserTurns.add(turnId);
        pushMessage({
          id: typeof clientMessageId === "string" && clientMessageId ? clientMessageId : `${turnId}:human`,
          role: "human",
          content: input,
          createdAt: event.created_at,
          status: "complete",
          attachments,
        }, eventIndex);
      }
    }
    if (event.event_type === "runtime.output.delta") {
      const text = deltaTextPayload(event);
      if (text) {
        flushToolSegment(turnId, true);
        const current = outputSegmentsByTurn.get(turnId);
        const index = nextOutputSegmentIndexByTurn.get(turnId) || 0;
        if (!current) {
          nextOutputSegmentIndexByTurn.set(turnId, index + 1);
        }
        outputSegmentsByTurn.set(turnId, {
          text: current ? `${current.text}${text}` : text,
          createdAt: event.created_at,
          order: current ? current.order : eventIndex,
          index: current ? current.index : index,
        });
      }
    }
    if (event.event_type === "runtime.output.final") {
      flushToolSegment(turnId, true);
      flushOutputSegment(turnId, true);
      const structured = structuredPayload(event.payload.structured_content || event.payload.structuredContent || event.payload.content);
      const finalText = textPayload(event);
      const text = finalTextRemainder(finalText, renderedOutputByTurn.get(turnId) || "");
      if (structured) {
        pushMessage({
          id: `${turnId}:structured:${event.event_id}`,
          role: "structured",
          content: text || finalText || structured.kind,
          createdAt: event.created_at,
          status: "complete",
          structuredContent: structured,
        }, eventIndex);
      }
      if (text) {
        pushMessage({
          id: `${turnId}:agent`,
          role: "agent",
          content: text,
          createdAt: event.created_at,
          status: "complete",
        }, eventIndex);
      }
      structuredContentFromAgentLinks(finalText).forEach((linkPreview, index) => {
        pushMessage({
          id: `${turnId}:link-preview:${event.event_id}:${index}`,
          role: "structured",
          content: linkPreview.kind,
          createdAt: event.created_at,
          status: "complete",
          structuredContent: linkPreview,
        }, eventIndex);
      });
    }
    const toolCall = toolCallPayload(event) || skillChangeToolCallPayload(event);
    if (toolCall) {
      flushOutputSegment(turnId, finalTurnIds.has(turnId));
      const current = toolSegmentsByTurn.get(turnId);
      const key = toolCallKey(toolCall);
      if (current) {
        const previous = current.itemsByKey.get(key);
        current.itemsByKey.set(key, previous ? mergeToolCall(previous, toolCall) : toolCall);
      } else {
        const index = nextToolSegmentIndexByTurn.get(turnId) || 0;
        nextToolSegmentIndexByTurn.set(turnId, index + 1);
        toolSegmentsByTurn.set(turnId, { createdAt: event.created_at, itemsByKey: new Map([[key, toolCall]]), index, order: eventIndex });
      }
      continue;
    }
    const step = stepPayload(event);
    if (step) {
      flushToolSegment(turnId, true);
      flushOutputSegment(turnId, finalTurnIds.has(turnId));
      pushMessage({
        id: `${turnId}:step:${event.event_id}`,
        role: "step",
        content: step.label,
        createdAt: event.created_at,
        status: "complete",
        step,
      }, eventIndex);
    }
    if (event.event_type === "runtime.turn.failed") {
      flushToolSegment(turnId, true);
      flushOutputSegment(turnId, true);
      const error = readableSystemText(event.payload.error || event.payload.exit_code, "Runtime turn failed.");
      pushMessage({
        id: `${turnId}:failed`,
        role: "system",
        content: error,
        createdAt: event.created_at,
        status: "failed",
      }, eventIndex);
    }
    if (event.event_type === "runtime.turn.cancelled") {
      flushToolSegment(turnId, true);
      flushOutputSegment(turnId, true);
      const reason = readableSystemText(event.payload.reason, "Runtime turn cancelled.");
      pushMessage({
        id: `${turnId}:cancelled`,
        role: "system",
        content: reason,
        createdAt: event.created_at,
        status: "failed",
      }, eventIndex);
    }
  }
  for (const turnId of outputSegmentsByTurn.keys()) {
    flushOutputSegment(turnId, finalTurnIds.has(turnId));
  }
  for (const turnId of toolSegmentsByTurn.keys()) {
    flushToolSegment(turnId);
  }
  orderedMessages.sort((left, right) => left.order - right.order || left.sequence - right.sequence);
  return orderedMessages.map((entry) => entry.message);
}

function finalTextRemainder(finalText: string, renderedText: string): string {
  if (!finalText || !renderedText) {
    return finalText;
  }
  if (finalText.startsWith(renderedText)) {
    return finalText.slice(renderedText.length).trimStart();
  }
  const whitespaceInsensitivePrefixEnd = prefixEndIgnoringWhitespace(finalText, renderedText);
  if (whitespaceInsensitivePrefixEnd !== null) {
    return finalText.slice(whitespaceInsensitivePrefixEnd).trimStart();
  }
  if (normalizedText(finalText) === normalizedText(renderedText)) {
    return "";
  }
  return finalText;
}

function prefixEndIgnoringWhitespace(text: string, prefix: string): number | null {
  let textIndex = 0;
  let prefixIndex = 0;
  while (prefixIndex < prefix.length) {
    const prefixChar = prefix[prefixIndex];
    if (/\s/.test(prefixChar)) {
      while (prefixIndex < prefix.length && /\s/.test(prefix[prefixIndex])) {
        prefixIndex += 1;
      }
      if (prefixIndex >= prefix.length) {
        while (textIndex < text.length && /\s/.test(text[textIndex])) {
          textIndex += 1;
        }
        return textIndex;
      }
      if (textIndex >= text.length || !/\s/.test(text[textIndex])) {
        return null;
      }
      while (textIndex < text.length && /\s/.test(text[textIndex])) {
        textIndex += 1;
      }
      continue;
    }
    if (text[textIndex] !== prefixChar) {
      return null;
    }
    textIndex += 1;
    prefixIndex += 1;
  }
  return textIndex;
}

function normalizedText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function firstUserTitle(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "New chat";
  }
  return normalized.length > 54 ? `${normalized.slice(0, 54)}...` : normalized;
}
