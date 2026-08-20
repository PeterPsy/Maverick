import type { AppReference, ChatMessage, RuntimeEvent, RuntimeStepMessage, StructuredContent, ToolCallMessage } from "../api/client";
import type { ChatMessageAttachment } from "../api/client";
import {
  goalTranscriptScope,
  goalTranscriptStep,
  isTerminalGoalStatus,
  mergeGoalTranscriptSteps,
} from "./goalTranscript";
import { structuredContentFromAgentLinks } from "./linkPreviews";
import { isNoisyRuntimeLabel, isNonChatFacingProviderEvent, runtimeStepLabel } from "./runtimeStepLabels";

const transcriptProjectionCache = new WeakMap<RuntimeEvent[], ChatMessage[]>();
const transcriptProjectionCacheByLastEvent = new Map<string, ChatMessage[]>();
const TRANSCRIPT_PROJECTION_CACHE_LIMIT = 80;

export function clearTranscriptProjectionCache(): void {
  transcriptProjectionCacheByLastEvent.clear();
}

function textPayload(event: RuntimeEvent): string {
  const value = event.payload.text;
  return meaningfulRuntimeText(value);
}

function completeTextPayload(event: RuntimeEvent): string {
  const value = event.payload.complete_text;
  return meaningfulRuntimeText(value);
}

function deltaTextPayload(event: RuntimeEvent): string {
  const value = event.payload.text;
  return typeof value === "string" ? removeNoisyRuntimeTextLines(value) : "";
}

function meaningfulRuntimeText(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  const filtered = removeNoisyRuntimeTextLines(value);
  return filtered.trim() ? filtered : "";
}

function removeNoisyRuntimeTextLines(value: string): string {
  return value
    .split(/\r?\n/)
    .filter((line) => {
      const trimmed = line.trim();
      return !trimmed || !isNoisyRuntimeLabel(trimmed);
    })
    .join("\n");
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

function stringPayload(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function isInterAgentParticipantProjection(event: RuntimeEvent): boolean {
  return event.payload.inter_agent_projection === "participant_runtime_event";
}

function messageTurnId(event: RuntimeEvent): string {
  const turnId = event.turn_id || event.event_id;
  if (!isInterAgentParticipantProjection(event)) {
    return turnId;
  }
  const blockId = stringPayload(event.payload.inter_agent_participant_block_id);
  return blockId ? `${turnId}:inter-agent:${blockId}` : turnId;
}

type MessageSourceFields = Pick<ChatMessage, "sourceLabel" | "sourceParticipantId" | "sourceRunId">;

function sourceFieldsForEvent(event: RuntimeEvent): MessageSourceFields {
  if (!isInterAgentParticipantProjection(event)) {
    return {};
  }
  const sourceLabel = stringPayload(event.payload.inter_agent_participant_label);
  const sourceParticipantId = stringPayload(event.payload.inter_agent_participant_id);
  const sourceRunId = stringPayload(event.payload.inter_agent_run_id);
  return {
    ...(sourceLabel ? { sourceLabel } : {}),
    ...(sourceParticipantId ? { sourceParticipantId } : {}),
    ...(sourceRunId ? { sourceRunId } : {}),
  };
}

function structuredPayloadKey(turnId: string, structured: StructuredContent): string {
  return `${turnId}:${JSON.stringify(structured)}`;
}

function toolCallPayload(event: RuntimeEvent): ToolCallMessage | null {
  if (!event.event_type.startsWith("runtime.tool_call.")) {
    return null;
  }
  if (isNonChatFacingToolEvent(event)) {
    return null;
  }
  const status = event.event_type.split(".").at(-1);
  if (status !== "started" && status !== "updated" && status !== "awaiting_confirmation" && status !== "completed" && status !== "failed") {
    return null;
  }
  const name = event.payload.name || event.payload.tool_name || event.payload.tool || event.payload.tool_handle;
  return {
    id: event.event_id,
    name: typeof name === "string" && name ? name : "tool",
    status,
    detail: { ...event.payload, turn_id: event.turn_id },
    createdAt: event.created_at,
  };
}

function isNonChatFacingToolEvent(event: RuntimeEvent): boolean {
  return isNonChatFacingProviderEvent(event.payload.provider_event_type) || isNonChatFacingProviderEvent(event.payload.name);
}

function stableToolCallKey(toolCall: ToolCallMessage): string | null {
  for (const key of ["invocation_id", "tool_call_id", "provider_tool_call_id", "call_id", "item_id"]) {
    const value = toolCall.detail[key];
    if (typeof value === "string" && value.trim()) {
      return `${key}:${value.trim()}`;
    }
  }
  return null;
}

function toolCallKey(toolCall: ToolCallMessage): string {
  const stableKey = stableToolCallKey(toolCall);
  if (stableKey) {
    return stableKey;
  }
  return `event:${toolCall.id}`;
}

function isFileChangeToolCall(toolCall: ToolCallMessage): boolean {
  return toolCall.detail.tool_kind === "file_change" || toolCall.name === "file_change";
}

function activeFileChangeToolCallKey(itemsByKey: Map<string, ToolCallMessage>): string | null {
  const entries = [...itemsByKey.entries()].reverse();
  const activeEntry = entries.find(([, item]) => isFileChangeToolCall(item) && (item.status === "started" || item.status === "updated"));
  return activeEntry?.[0] || null;
}

function segmentToolCallKey(itemsByKey: Map<string, ToolCallMessage>, toolCall: ToolCallMessage): string {
  const stableKey = stableToolCallKey(toolCall);
  if (stableKey && itemsByKey.has(stableKey)) {
    return stableKey;
  }
  if (isFileChangeToolCall(toolCall) && toolCall.status !== "started") {
    const activeKey = activeFileChangeToolCallKey(itemsByKey);
    if (activeKey) {
      return activeKey;
    }
  }
  return stableKey || toolCallKey(toolCall);
}

function mergeToolCall(previous: ToolCallMessage, next: ToolCallMessage): ToolCallMessage {
  const statusRank: Record<ToolCallMessage["status"], number> = {
    started: 1,
    updated: 2,
    awaiting_confirmation: 3,
    completed: 4,
    failed: 5,
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
  if (event.event_type === "provider.usage") {
    return null;
  }
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

function appReferencesPayload(value: unknown): AppReference[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map(appReferencePayload)
    .filter((item) => (item.type === "app" ? Boolean(item.app_id) : Boolean(item.app_id && item.entity_type && item.entity_id)));
}

function appReferencePayload(item: Record<string, unknown>): AppReference {
  const appId = typeof item.app_id === "string" ? item.app_id : "";
  if (item.type === "entity") {
    return {
      type: "entity",
      app_id: appId,
      entity_type: typeof item.entity_type === "string" ? item.entity_type : "",
      entity_id: typeof item.entity_id === "string" ? item.entity_id : "",
      label: typeof item.label === "string" ? item.label : "",
      summary: typeof item.summary === "string" ? item.summary : undefined,
      deep_link: typeof item.deep_link === "string" ? item.deep_link : undefined,
      exists: typeof item.exists === "boolean" ? item.exists : undefined,
    };
  }
  return {
    type: "app",
    app_id: appId,
    label: typeof item.label === "string" ? item.label : undefined,
  };
}

export function eventsToMessages(events: RuntimeEvent[]): ChatMessage[] {
  const cached = transcriptProjectionCache.get(events);
  if (cached) {
    return cached;
  }
  const cacheKey = transcriptProjectionCacheKey(events);
  const cachedByLastEvent = transcriptProjectionCacheByLastEvent.get(cacheKey);
  if (cachedByLastEvent) {
    transcriptProjectionCache.set(events, cachedByLastEvent);
    transcriptProjectionCacheByLastEvent.delete(cacheKey);
    transcriptProjectionCacheByLastEvent.set(cacheKey, cachedByLastEvent);
    return cachedByLastEvent;
  }
  const messages = projectEventsToMessages(events);
  transcriptProjectionCache.set(events, messages);
  transcriptProjectionCacheByLastEvent.set(cacheKey, messages);
  while (transcriptProjectionCacheByLastEvent.size > TRANSCRIPT_PROJECTION_CACHE_LIMIT) {
    const oldestKey = transcriptProjectionCacheByLastEvent.keys().next().value;
    if (!oldestKey) {
      break;
    }
    transcriptProjectionCacheByLastEvent.delete(oldestKey);
  }
  return messages;
}

function transcriptProjectionCacheKey(events: RuntimeEvent[]): string {
  if (!events.length) {
    return "empty";
  }
  const first = events[0];
  const last = events[events.length - 1];
  return [first.session_id, first.event_id, events.length, last.session_id, last.event_id, last.created_at].join(":");
}

function projectEventsToMessages(events: RuntimeEvent[]): ChatMessage[] {
  type OrderedMessage = { order: number; sequence: number; message: ChatMessage };

  const orderedMessages: OrderedMessage[] = [];
  let messageSequence = 0;
  const seenUserMessages = new Set<string>();
  const finalTurnIds = new Set(events.filter((event) => event.event_type === "runtime.output.final").map(messageTurnId));
  const outputSegmentsByTurn = new Map<
    string,
    { text: string; createdAt: string; index: number; order: number; sourceFields: MessageSourceFields }
  >();
  const nextOutputSegmentIndexByTurn = new Map<string, number>();
  const renderedOutputByTurn = new Map<string, string>();
  const toolSegmentsByTurn = new Map<
    string,
    { createdAt: string; itemsByKey: Map<string, ToolCallMessage>; index: number; order: number; sourceFields: MessageSourceFields }
  >();
  const nextToolSegmentIndexByTurn = new Map<string, number>();
  const renderedStructuredOutput = new Set<string>();
  const activeGoalMessages = new Map<string, OrderedMessage>();

  function pushMessage(message: ChatMessage, order: number): OrderedMessage {
    const entry = { order, sequence: messageSequence, message };
    orderedMessages.push(entry);
    messageSequence += 1;
    return entry;
  }

  function removeMessage(entry: OrderedMessage) {
    const index = orderedMessages.indexOf(entry);
    if (index >= 0) {
      orderedMessages.splice(index, 1);
    }
  }

  function appendRenderedOutput(turnId: string, text: string) {
    if (text) {
      renderedOutputByTurn.set(turnId, `${renderedOutputByTurn.get(turnId) || ""}${text}`);
    }
  }

  function removeRenderedOutputMessages(turnId: string) {
    const streamPrefix = `${turnId}:agent:stream:`;
    for (let index = orderedMessages.length - 1; index >= 0; index -= 1) {
      if (orderedMessages[index].message.id.startsWith(streamPrefix)) {
        orderedMessages.splice(index, 1);
      }
    }
    renderedOutputByTurn.delete(turnId);
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
      ...segment.sourceFields,
    }, segment.order);
    appendRenderedOutput(turnId, segment.text);
    if (closeActive) {
      pushLinkPreviews(turnId, `stream:${segment.index}`, segment.text, segment.order, segment.createdAt, segment.sourceFields);
    }
    outputSegmentsByTurn.delete(turnId);
  }

  function pushLinkPreviews(
    turnId: string,
    sourceId: string,
    text: string,
    order: number,
    createdAt: string,
    sourceFields: MessageSourceFields = {},
  ) {
    structuredContentFromAgentLinks(text).forEach((linkPreview, index) => {
      const structuredKey = structuredPayloadKey(turnId, linkPreview);
      if (renderedStructuredOutput.has(structuredKey)) {
        return;
      }
      renderedStructuredOutput.add(structuredKey);
      pushMessage({
        id: `${turnId}:link-preview:${sourceId}:${index}`,
        role: "structured",
        content: linkPreview.kind,
        createdAt,
        status: "complete",
        structuredContent: linkPreview,
        ...sourceFields,
      }, order);
    });
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
      const hasPendingConfirmation = items.some((item) => item.status === "awaiting_confirmation");
      pushMessage({
        id: `${turnId}:tools:${segment.index}`,
        role: "tool",
        content: "Tool Used",
        createdAt: segment.createdAt,
        status: hasFailedTool ? "failed" : hasPendingConfirmation ? "pending" : "complete",
        toolCalls: items,
        toolCall: items[0],
        ...segment.sourceFields,
      }, segment.order);
    }
    toolSegmentsByTurn.delete(turnId);
  }

  for (const [eventIndex, event] of events.entries()) {
    const turnId = messageTurnId(event);
    const sourceFields = sourceFieldsForEvent(event);
    if (event.event_type === "runtime.turn.queued" || event.event_type === "runtime.message.steered") {
      const input = event.payload.input_text;
      const clientMessageId = event.payload.client_message_id;
      const userMessageId =
        typeof clientMessageId === "string" && clientMessageId
          ? clientMessageId
          : event.event_type === "runtime.turn.queued"
            ? `${turnId}:human`
            : `${turnId}:human:${event.event_id}`;
      const attachments = Array.isArray(event.payload.attachments)
        ? (event.payload.attachments.filter((item) => item && typeof item === "object") as ChatMessageAttachment[])
        : [];
      const appReferences = appReferencesPayload(event.payload.app_references);
      const hasDisplayContent =
        (typeof input === "string" && Boolean(input.trim())) || attachments.length > 0 || appReferences.length > 0;
      if (hasDisplayContent && !seenUserMessages.has(userMessageId)) {
        if (event.event_type === "runtime.message.steered") {
          flushToolSegment(turnId, true);
          flushOutputSegment(turnId, true);
        }
        seenUserMessages.add(userMessageId);
        pushMessage({
          id: userMessageId,
          role: "human",
          content: typeof input === "string" ? input : "",
          createdAt: event.created_at,
          status: "complete",
          attachments,
          appReferences,
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
          sourceFields: current?.sourceFields || sourceFields,
        });
      }
    }
    if (event.event_type === "runtime.output.structured") {
      flushToolSegment(turnId, true);
      flushOutputSegment(turnId, finalTurnIds.has(turnId));
      const structured = structuredPayload(event.payload.structured_content || event.payload.structuredContent || event.payload.content);
      if (structured) {
        renderedStructuredOutput.add(structuredPayloadKey(turnId, structured));
        pushMessage({
          id: `${turnId}:structured:${event.event_id}`,
          role: "structured",
          content: structured.kind,
          createdAt: event.created_at,
          status: "complete",
          structuredContent: structured,
          ...sourceFields,
        }, eventIndex);
      }
    }
    if (event.event_type === "runtime.output.final") {
      flushToolSegment(turnId, true);
      flushOutputSegment(turnId, true);
      const finalProjection = finalOutputProjection(event, renderedOutputByTurn.get(turnId) || "");
      if (finalProjection.replaceRenderedOutput) {
        removeRenderedOutputMessages(turnId);
      }
      const finalText = finalProjection.previewText;
      const structured = structuredPayload(event.payload.structured_content || event.payload.structuredContent || event.payload.content);
      const text = finalProjection.text;
      const structuredKey = structured ? structuredPayloadKey(turnId, structured) : "";
      const structuredAlreadyRendered = Boolean(structuredKey) && renderedStructuredOutput.has(structuredKey);
      const shouldPushStructured = Boolean(structured) && !structuredAlreadyRendered;
      if (structured && shouldPushStructured) {
        renderedStructuredOutput.add(structuredKey);
        pushMessage({
          id: `${turnId}:structured:${event.event_id}`,
          role: "structured",
          content: text || finalText || structured.kind,
          createdAt: event.created_at,
          status: "complete",
          structuredContent: structured,
          ...sourceFields,
        }, eventIndex);
      }
      if (text) {
        pushMessage({
          id: `${turnId}:agent`,
          role: "agent",
          content: text,
          createdAt: event.created_at,
          status: "complete",
          ...sourceFields,
        }, eventIndex);
      }
      pushLinkPreviews(turnId, event.event_id, finalText, eventIndex, event.created_at, sourceFields);
    }
    const toolCall = toolCallPayload(event);
    if (toolCall) {
      flushOutputSegment(turnId, finalTurnIds.has(turnId));
      const current = toolSegmentsByTurn.get(turnId);
      if (current) {
        const key = segmentToolCallKey(current.itemsByKey, toolCall);
        const previous = current.itemsByKey.get(key);
        current.itemsByKey.set(key, previous ? mergeToolCall(previous, toolCall) : toolCall);
      } else {
        const key = toolCallKey(toolCall);
        const index = nextToolSegmentIndexByTurn.get(turnId) || 0;
        nextToolSegmentIndexByTurn.set(turnId, index + 1);
        toolSegmentsByTurn.set(turnId, {
          createdAt: event.created_at,
          itemsByKey: new Map([[key, toolCall]]),
          index,
          order: eventIndex,
          sourceFields,
        });
      }
      continue;
    }
    const goalUpdate = goalTranscriptStep(event);
    if (goalUpdate) {
      const goalScope = goalTranscriptScope(event);
      const activeGoal = activeGoalMessages.get(goalScope);
      if (goalUpdate.cleared) {
        if (activeGoal) {
          removeMessage(activeGoal);
          activeGoalMessages.delete(goalScope);
        }
        continue;
      }
      if (activeGoal) {
        if (goalUpdate.hasDisplayState || goalUpdate.hasUsage) {
          const mergedStep = mergeGoalTranscriptSteps(activeGoal.message.step!, goalUpdate.step);
          activeGoal.message.content = mergedStep.label;
          activeGoal.message.step = mergedStep;
          const mergedStatus = goalTranscriptStep({ ...event, payload: mergedStep.detail })?.status || "";
          if (isTerminalGoalStatus(mergedStatus)) {
            activeGoalMessages.delete(goalScope);
          }
        }
        continue;
      }
      if (!goalUpdate.hasDisplayState) {
        continue;
      }
      flushToolSegment(turnId, true);
      flushOutputSegment(turnId, finalTurnIds.has(turnId));
      const goalMessage = pushMessage({
        id: `${turnId}:step:${event.event_id}`,
        role: "step",
        content: goalUpdate.step.label,
        createdAt: event.created_at,
        status: "complete",
        step: goalUpdate.step,
        ...sourceFields,
      }, eventIndex);
      if (!isTerminalGoalStatus(goalUpdate.status)) {
        activeGoalMessages.set(goalScope, goalMessage);
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
        ...sourceFields,
      }, eventIndex);
    }
    if (event.event_type === "runtime.turn.failed") {
      flushToolSegment(turnId, true);
      flushOutputSegment(turnId, true);
      const error = readableSystemText(event.payload.error, "Runtime turn failed.");
      pushMessage({
        id: `${turnId}:failed`,
        role: "system",
        content: error,
        createdAt: event.created_at,
        status: "failed",
        ...sourceFields,
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
        ...sourceFields,
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

function finalOutputProjection(event: RuntimeEvent, renderedText: string): { text: string; previewText: string; replaceRenderedOutput: boolean } {
  const finalText = textPayload(event);
  const completeText = completeTextPayload(event);
  if (finalText) {
    if (completeText && renderedText && textStartsWithRenderedText(completeText, renderedText)) {
      const completeRemainder = finalTextRemainder(completeText, renderedText);
      if (!completeRemainder || completeRemainder.endsWith(finalText)) {
        return { text: completeRemainder, previewText: completeText, replaceRenderedOutput: false };
      }
    }
    return {
      text: finalTextRemainder(finalText, renderedText),
      previewText: completeText || finalText,
      replaceRenderedOutput: false,
    };
  }
  if (!completeText) {
    return { text: "", previewText: "", replaceRenderedOutput: false };
  }
  if (!renderedText) {
    return { text: completeText, previewText: completeText, replaceRenderedOutput: false };
  }
  if (textStartsWithRenderedText(completeText, renderedText)) {
    return {
      text: finalTextRemainder(completeText, renderedText),
      previewText: completeText,
      replaceRenderedOutput: false,
    };
  }
  return { text: completeText, previewText: completeText, replaceRenderedOutput: true };
}

function finalTextRemainder(finalText: string, renderedText: string): string {
  if (!finalText || !renderedText) {
    return finalText;
  }
  if (finalText.startsWith(renderedText)) {
    return finalText.slice(renderedText.length);
  }
  const whitespaceInsensitivePrefixEnd = prefixEndIgnoringWhitespace(finalText, renderedText);
  if (whitespaceInsensitivePrefixEnd !== null) {
    return finalText.slice(whitespaceInsensitivePrefixEnd);
  }
  if (normalizedText(finalText) === normalizedText(renderedText)) {
    return "";
  }
  return finalText;
}

function textStartsWithRenderedText(text: string, renderedText: string): boolean {
  if (!text || !renderedText) {
    return false;
  }
  return text.startsWith(renderedText) || prefixEndIgnoringWhitespace(text, renderedText) !== null || normalizedText(text) === normalizedText(renderedText);
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
