import type { RuntimeEvent, RuntimeTurn } from "../api/client";
import { equivalentEvent } from "./transcriptProjection";

const SYNTHETIC_TURN_ANCHOR_PREFIX = "synthetic-turn-anchor:";
const SYNTHETIC_TURN_STATUS_PREFIX = "synthetic-turn-status:";

type EventIndex = { owner: RuntimeEvent[]; byId: Map<string, RuntimeEvent> };
const eventIndexes = new WeakMap<RuntimeEvent[], EventIndex>();

function compareEvents(left: RuntimeEvent, right: RuntimeEvent): number {
  return left.created_at.localeCompare(right.created_at) || left.event_id.localeCompare(right.event_id);
}

export function mergeRuntimeEvents(current: RuntimeEvent[], incoming: RuntimeEvent[]): RuntimeEvent[] {
  if (!incoming.length) return current;
  let index = eventIndexes.get(current);
  if (!index || index.owner !== current) index = { owner: current, byId: new Map(current.map(event => [event.event_id, event])) };
  const changed = new Map<string, RuntimeEvent>();
  for (const event of incoming) {
    const previous = changed.get(event.event_id) || index.byId.get(event.event_id);
    if (!previous || !equivalentEvent(previous, event)) changed.set(event.event_id, event);
  }
  if (!changed.size) return current;
  const appended = [...changed.values()];
  const tail = current.at(-1);
  const isAppend = appended.every(event => !index.byId.has(event.event_id) && (!tail || compareEvents(tail, event) < 0));
  for (const event of appended) index.byId.set(event.event_id, event);
  // The live path sorts only this frame's new events. Replayed/corrected events
  // still use a deterministic full merge; duplicate replay preserves identity.
  const result = isAppend ? current.concat(appended.sort(compareEvents)) : [...index.byId.values()].sort(compareEvents);
  index.owner = result;
  eventIndexes.set(result, index);
  return result;
}

export function lastRuntimeEventId(events: RuntimeEvent[]): string | null {
  return events.length ? events[events.length - 1].event_id : null;
}

export function firstRuntimeEventId(events: RuntimeEvent[]): string | null {
  return events.length ? events[0].event_id : null;
}

export function firstPersistedRuntimeEventId(events: RuntimeEvent[]): string | null {
  return events.find((event) => !isSyntheticRuntimeEvent(event))?.event_id || null;
}

export function isSyntheticRuntimeEvent(event: RuntimeEvent): boolean {
  return event.event_id.startsWith('display:') || event.event_id.startsWith(SYNTHETIC_TURN_ANCHOR_PREFIX)
    || event.event_id.startsWith(SYNTHETIC_TURN_STATUS_PREFIX);
}

export function hydrateMissingTurnAnchors(events: RuntimeEvent[], turns: RuntimeTurn[] | undefined): RuntimeEvent[] {
  if (!events.length || !turns?.length) {
    return events;
  }
  const eventsByTurnId = new Map<string, RuntimeEvent[]>();
  for (const event of events) {
    if (!event.turn_id) {
      continue;
    }
    const turnEvents = eventsByTurnId.get(event.turn_id) || [];
    turnEvents.push(event);
    eventsByTurnId.set(event.turn_id, turnEvents);
  }
  if (!eventsByTurnId.size) {
    return events;
  }
  const queuedTurnIds = new Set(
    events
      .filter((event) => event.turn_id && event.event_type === "runtime.turn.queued")
      .map((event) => event.turn_id as string),
  );
  const terminalTurnIds = new Set(
    events
      .filter((event) => event.turn_id && isTerminalRuntimeEvent(event))
      .map((event) => event.turn_id as string),
  );
  const syntheticEvents: RuntimeEvent[] = [];
  for (const turn of turns) {
    const turnEvents = eventsByTurnId.get(turn.turn_id);
    if (!turnEvents) {
      continue;
    }
    if (!queuedTurnIds.has(turn.turn_id) && Boolean(turn.input_text?.trim())) {
      syntheticEvents.push(syntheticTurnAnchor(turn));
    }
    const terminalEventType = terminalEventTypeForTurnStatus(turn.status);
    if (terminalEventType && !terminalTurnIds.has(turn.turn_id)) {
      syntheticEvents.push(syntheticTurnStatusEvent(turn, terminalEventType, turnEvents));
    }
  }
  return syntheticEvents.length ? mergeRuntimeEvents(events, syntheticEvents) : events;
}

function syntheticTurnAnchor(turn: RuntimeTurn): RuntimeEvent {
  const payload: Record<string, unknown> = {
    input_text: turn.input_text || "",
    synthetic_turn_anchor: true,
  };
  if (turn.client_message_id) {
    payload.client_message_id = turn.client_message_id;
  }
  return {
    event_id: `${SYNTHETIC_TURN_ANCHOR_PREFIX}${turn.turn_id}`,
    session_id: turn.session_id,
    turn_id: turn.turn_id,
    event_type: "runtime.turn.queued",
    payload,
    created_at: turn.created_at,
  };
}

function syntheticTurnStatusEvent(turn: RuntimeTurn, eventType: string, turnEvents: RuntimeEvent[]): RuntimeEvent {
  const payload: Record<string, unknown> = {
    status: turn.status,
    synthetic_turn_status: true,
  };
  if (turn.failure_reason) {
    payload.error = turn.failure_reason;
  }
  return {
    event_id: `${SYNTHETIC_TURN_STATUS_PREFIX}${turn.turn_id}`,
    session_id: turn.session_id,
    turn_id: turn.turn_id,
    event_type: eventType,
    payload,
    created_at: latestRuntimeTimestamp([turn.created_at, turn.updated_at, ...turnEvents.map((event) => event.created_at)]),
  };
}

function latestRuntimeTimestamp(timestamps: string[]): string {
  return timestamps.filter(Boolean).sort().at(-1) || "";
}

export function liveRuntimeTurnAfterEvents(events: RuntimeEvent[], current: RuntimeTurn | null, sessionId: string): RuntimeTurn | null {
  const anchor = current ? { ...syntheticTurnAnchor(current),
    event_type: current.status === 'queued' ? 'runtime.turn.queued' : 'runtime.turn.started' } : null;
  return inferActiveRuntimeTurn(anchor ? [anchor, ...events] : events, sessionId);
}

export function inferActiveRuntimeTurn(events: RuntimeEvent[], sessionId: string | null): RuntimeTurn | null {
  if (!sessionId) {
    return null;
  }
  const turns = new Map<string, RuntimeTurn>();
  for (const event of events) {
    if (!event.turn_id) {
      const eventStatus = event.session_id === sessionId ? runtimeTurnStatusFromEvent(event) : null;
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
    const eventStatus = runtimeTurnStatusFromEvent(event);
    const status = selectRuntimeTurnStatus(previous?.status || null, eventStatus) || "queued";
    turns.set(event.turn_id, {
      turn_id: event.turn_id,
      session_id: sessionId,
      workspace_id: typeof event.payload.workspace_id === "string" ? event.payload.workspace_id : "",
      status,
      client_message_id: typeof event.payload.client_message_id === "string" ? event.payload.client_message_id : previous?.client_message_id,
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

export function runtimeTurnStatusFromEvent(event: RuntimeEvent): RuntimeTurn["status"] | null {
  if (event.payload.inter_agent_projection === "participant_runtime_event") {
    return null;
  }
  return turnStatusFromEventType(event.event_type);
}

function turnStatusFromEventType(eventType: string): RuntimeTurn["status"] | null {
  if (eventType === "runtime.turn.queued") {
    return "queued";
  }
  if (eventType === "runtime.turn.started") {
    return "active";
  }
  if (eventType === "runtime.output.final") {
    return "completed";
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
  if (eventType === "runtime.turn.timed-out") {
    return "timed-out";
  }
  return null;
}

function isTerminalRuntimeEvent(event: RuntimeEvent): boolean {
  const status = runtimeTurnStatusFromEvent(event);
  return Boolean(status && turnStatusRank(status) >= turnStatusRank("completed"));
}

function terminalEventTypeForTurnStatus(status: RuntimeTurn["status"]): string | null {
  if (status === "completed") {
    return "runtime.turn.completed";
  }
  if (status === "failed") {
    return "runtime.turn.failed";
  }
  if (status === "cancelled") {
    return "runtime.turn.cancelled";
  }
  if (status === "timed-out") {
    return "runtime.turn.timed-out";
  }
  return null;
}
