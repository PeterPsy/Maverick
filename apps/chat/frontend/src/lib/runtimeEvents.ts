import type { RuntimeEvent, RuntimeTurn } from "../api/client";

export function mergeRuntimeEvents(current: RuntimeEvent[], incoming: RuntimeEvent[]): RuntimeEvent[] {
  const byId = new Map<string, RuntimeEvent>();
  for (const event of current) {
    byId.set(event.event_id, event);
  }
  for (const event of incoming) {
    byId.set(event.event_id, event);
  }
  return Array.from(byId.values()).sort((left, right) => {
    const byCreatedAt = left.created_at.localeCompare(right.created_at);
    return byCreatedAt || left.event_id.localeCompare(right.event_id);
  });
}

export function lastRuntimeEventId(events: RuntimeEvent[]): string | null {
  return events.length ? events[events.length - 1].event_id : null;
}

export function inferActiveRuntimeTurn(events: RuntimeEvent[], sessionId: string | null): RuntimeTurn | null {
  if (!sessionId) {
    return null;
  }
  const turns = new Map<string, RuntimeTurn>();
  for (const event of events) {
    if (!event.turn_id) {
      const eventStatus = event.session_id === sessionId ? turnStatusFromEvent(event.event_type) : null;
      if (eventStatus && turnStatusRank(eventStatus) >= turnStatusRank("completed")) {
        const activeTurn = [...turns.values()].filter((turn) => turn.status === "queued" || turn.status === "active").at(-1);
        if (activeTurn) {
          turns.set(activeTurn.turn_id, {
            ...activeTurn,
            status: eventStatus,
            failure_reason: typeof event.payload.error === "string" ? event.payload.error : activeTurn.failure_reason,
            updated_at: event.created_at,
          });
        }
      }
      continue;
    }
    const previous = turns.get(event.turn_id);
    const eventStatus = turnStatusFromEvent(event.event_type);
    const status = selectRuntimeTurnStatus(previous?.status || null, eventStatus) || "queued";
    turns.set(event.turn_id, {
      turn_id: event.turn_id,
      session_id: sessionId,
      workspace_id: typeof event.payload.workspace_id === "string" ? event.payload.workspace_id : "",
      status,
      input_text: typeof event.payload.input_text === "string" ? event.payload.input_text : previous?.input_text || null,
      failure_reason: typeof event.payload.error === "string" ? event.payload.error : previous?.failure_reason || null,
      created_at: previous?.created_at || event.created_at,
      updated_at: event.created_at,
    });
  }
  const activeTurns = [...turns.values()].filter((turn) => turn.status === "queued" || turn.status === "active");
  return activeTurns.at(-1) || null;
}

function selectRuntimeTurnStatus(currentStatus: RuntimeTurn["status"] | null, eventStatus: RuntimeTurn["status"] | null): RuntimeTurn["status"] | null {
  if (!currentStatus) {
    return eventStatus;
  }
  if (!eventStatus) {
    return currentStatus;
  }
  return turnStatusRank(eventStatus) >= turnStatusRank(currentStatus) ? eventStatus : currentStatus;
}

function turnStatusRank(status: RuntimeTurn["status"]): number {
  if (status === "queued") {
    return 1;
  }
  if (status === "active") {
    return 2;
  }
  return 3;
}

function turnStatusFromEvent(eventType: string): RuntimeTurn["status"] | null {
  if (eventType === "runtime.turn.queued") {
    return "queued";
  }
  if (eventType === "runtime.turn.started") {
    return "active";
  }
  if (eventType === "runtime.turn.completed") {
    return "completed";
  }
  if (eventType === "runtime.turn.failed") {
    return "failed";
  }
  if (eventType === "runtime.turn.cancelled") {
    return "cancelled";
  }
  return null;
}
