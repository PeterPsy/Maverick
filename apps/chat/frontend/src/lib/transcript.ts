import type { ChatMessage, RuntimeEvent } from "../api/client";

function textPayload(event: RuntimeEvent): string {
  const value = event.payload.text;
  return typeof value === "string" ? value.trim() : "";
}

export function eventsToMessages(events: RuntimeEvent[]): ChatMessage[] {
  const messages: ChatMessage[] = [];
  const seenUserTurns = new Set<string>();
  for (const event of events) {
    const turnId = event.turn_id || event.event_id;
    if (event.event_type === "runtime.turn.queued" && !seenUserTurns.has(turnId)) {
      const input = event.payload.input_text;
      if (typeof input === "string" && input.trim()) {
        seenUserTurns.add(turnId);
        messages.push({
          id: `${turnId}:human`,
          role: "human",
          content: input,
          createdAt: event.created_at,
          status: "complete",
        });
      }
    }
    if (event.event_type === "runtime.output.final") {
      const text = textPayload(event);
      if (text) {
        messages.push({
          id: `${turnId}:agent`,
          role: "agent",
          content: text,
          createdAt: event.created_at,
          status: "complete",
        });
      }
    }
    if (event.event_type === "runtime.turn.failed") {
      const error = event.payload.error || event.payload.exit_code || "Runtime turn failed.";
      messages.push({
        id: `${turnId}:failed`,
        role: "system",
        content: String(error),
        createdAt: event.created_at,
        status: "failed",
      });
    }
  }
  return messages;
}

export function firstUserTitle(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "New chat";
  }
  return normalized.length > 54 ? `${normalized.slice(0, 54)}...` : normalized;
}
