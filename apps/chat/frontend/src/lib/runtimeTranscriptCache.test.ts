import { describe, expect, it } from "vitest";
import type { RuntimeEvent } from "../api/client";
import {
  deleteStoredRuntimeTranscript,
  normalizeRuntimeTranscriptCacheEntry,
  readStoredRuntimeTranscript,
  writeStoredRuntimeTranscript,
} from "./runtimeTranscriptCache";

function event(index: number): RuntimeEvent {
  return {
    event_id: `event-${index}`,
    session_id: "session-1",
    turn_id: "turn-1",
    event_type: "runtime.output.delta",
    payload: { text: String(index) },
    created_at: `2026-04-19T10:${String(index % 60).padStart(2, "0")}:00Z`,
  };
}

function storage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    removeItem: (key: string) => {
      values.delete(key);
    },
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

describe("runtime transcript cache", () => {
  it("round-trips a transcript snapshot through session storage", () => {
    const fakeStorage = storage();
    writeStoredRuntimeTranscript(
      "session-1",
      {
        activeSession: { agent_id: "chat", effective_mode: "runtime", session_id: "session-1", status: "active", workspace_id: "default" },
        activeTurn: null,
        events: [event(1)],
        hasLoadedHistory: false,
      },
      fakeStorage,
    );

    expect(readStoredRuntimeTranscript("session-1", fakeStorage)).toMatchObject({
      activeSession: { session_id: "session-1" },
      events: [{ event_id: "event-1" }],
      hasLoadedHistory: false,
      hasMoreHistory: false,
    });
  });

  it("does not treat partial cached events as complete loaded history", () => {
    const normalized = normalizeRuntimeTranscriptCacheEntry({
      activeSession: null,
      activeTurn: null,
      events: [event(1)],
      hasLoadedHistory: false,
    });

    expect(normalized.hasLoadedHistory).toBe(false);
  });

  it("preserves explicit older-history metadata", () => {
    const fakeStorage = storage();
    writeStoredRuntimeTranscript(
      "session-1",
      { activeSession: null, activeTurn: null, events: [event(1)], hasLoadedHistory: true, hasMoreHistory: true },
      fakeStorage,
    );

    expect(readStoredRuntimeTranscript("session-1", fakeStorage)).toMatchObject({
      events: [{ event_id: "event-1" }],
      hasLoadedHistory: true,
      hasMoreHistory: true,
    });
  });

  it("limits stored events to the latest transcript window", () => {
    const normalized = normalizeRuntimeTranscriptCacheEntry({
      activeSession: null,
      activeTurn: null,
      events: Array.from({ length: 320 }, (_, index) => event(index)),
      hasLoadedHistory: true,
    });

    expect(normalized.events).toHaveLength(300);
    expect(normalized.events[0].event_id).toBe("event-20");
    expect(normalized.events.at(-1)?.event_id).toBe("event-319");
  });

  it("drops corrupted entries instead of throwing", () => {
    const fakeStorage = storage();
    fakeStorage.setItem("maverick.chat.runtime-transcript-cache.v2:session-1", "{not json");

    expect(readStoredRuntimeTranscript("session-1", fakeStorage)).toBeNull();
    expect(readStoredRuntimeTranscript("session-1", fakeStorage)).toBeNull();
  });

  it("deletes stored transcripts by runtime session id", () => {
    const fakeStorage = storage();
    writeStoredRuntimeTranscript(
      "session-1",
      { activeSession: null, activeTurn: null, events: [event(1)], hasLoadedHistory: true },
      fakeStorage,
    );

    deleteStoredRuntimeTranscript("session-1", fakeStorage);

    expect(readStoredRuntimeTranscript("session-1", fakeStorage)).toBeNull();
  });
});
