import { describe, expect, it } from "vitest";
import type { ChatProject, ChatThread, RuntimeEvent } from "../../api/client";
import { buildSearchSections, searchChatThreads, threadLastMessageTimestamp, transcriptSearchTextFromEvents } from "./search";

function thread(overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    agent_label: "",
    agent_role_id: "",
    agent_type_id: "",
    archived: false,
    availability: "free",
    created_at: "2026-05-21T00:00:00Z",
    last_completed_response_at: null,
    last_user_message_at: null,
    project_id: null,
    runtime_session_id: "session-1",
    source_app_id: "chat",
    system_prompt: "",
    thread_id: "thread-1",
    title: "Budget notes",
    updated_at: "2026-05-21T00:00:00Z",
    ...overrides,
  };
}

function project(overrides: Partial<ChatProject> = {}): ChatProject {
  return {
    project_id: "project-1",
    name: "Client Work",
    created_at: "2026-05-21T00:00:00Z",
    updated_at: "2026-05-21T00:00:00Z",
    ...overrides,
  };
}

function event(overrides: Partial<RuntimeEvent>): RuntimeEvent {
  return {
    event_id: "event-1",
    session_id: "session-1",
    turn_id: "turn-1",
    event_type: "runtime.turn.queued",
    payload: {},
    created_at: "2026-05-21T00:00:00Z",
    ...overrides,
  };
}

describe("chat sidebar search ranking", () => {
  it("matches transcript text and orders stronger matches before newer weaker matches", () => {
    const olderExactTitle = thread({
      thread_id: "older-title",
      title: "Budget forecast",
      last_user_message_at: "2026-05-21T10:00:00Z",
      runtime_session_id: "session-older",
    });
    const newerTranscript = thread({
      thread_id: "newer-transcript",
      title: "Planning",
      last_completed_response_at: "2026-05-22T10:00:00Z",
      runtime_session_id: "session-newer",
    });

    const results = searchChatThreads({
      projectNames: new Map(),
      query: "budget forecast",
      threads: [olderExactTitle, newerTranscript],
      transcriptTextByThreadId: {
        "older-title": "budget forecast",
        "newer-transcript": "The budget forecast was updated.",
      },
    });

    expect(results.map((item) => item.thread.thread_id)).toEqual(["older-title", "newer-transcript"]);
    expect(results[0].score).toBeGreaterThan(results[1].score);
    expect(results[1].lastMessageAt).toBeGreaterThan(results[0].lastMessageAt);
  });

  it("orders equally strong matches by latest message timestamp", () => {
    const olderTitle = thread({
      thread_id: "older-title",
      title: "Budget forecast",
      last_user_message_at: "2026-05-21T10:00:00Z",
      runtime_session_id: "session-older",
    });
    const newerTitle = thread({
      thread_id: "newer-title",
      title: "Budget forecast",
      last_completed_response_at: "2026-05-22T10:00:00Z",
      runtime_session_id: "session-newer",
    });

    const results = searchChatThreads({
      projectNames: new Map(),
      query: "budget forecast",
      threads: [olderTitle, newerTitle],
      transcriptTextByThreadId: {},
    });

    expect(results.map((item) => item.thread.thread_id)).toEqual(["newer-title", "older-title"]);
    expect(results[0].score).toBe(results[1].score);
  });

  it("matches project names without showing project move controls in the virtual results section", () => {
    const sections = buildSearchSections({
      projects: [project({ project_id: "project-1", name: "Riepilogo Clienti" })],
      query: "clienti",
      threads: [thread({ project_id: "project-1" })],
      transcriptTextByThreadId: {},
    });

    expect(sections).toHaveLength(1);
    expect(sections[0]).toMatchObject({
      id: "search-results",
      title: "Search results",
      canCreateProject: false,
      canMoveThreads: false,
    });
    expect(sections[0].items.map((item) => item.thread_id)).toEqual(["thread-1"]);
  });

  it("uses the latest user or completed response time as the last message timestamp", () => {
    expect(
      threadLastMessageTimestamp(
        thread({
          created_at: "2026-05-21T08:00:00Z",
          updated_at: "2026-05-21T09:00:00Z",
          last_user_message_at: "2026-05-21T10:00:00Z",
          last_completed_response_at: "2026-05-21T11:00:00Z",
        }),
      ),
    ).toBe(Date.parse("2026-05-21T11:00:00Z"));
  });

  it("projects user and agent transcript events into searchable text", () => {
    const text = transcriptSearchTextFromEvents([
      event({
        event_id: "queued",
        event_type: "runtime.turn.queued",
        payload: { input_text: "Analisi vendite" },
      }),
      event({
        event_id: "final",
        event_type: "runtime.output.final",
        payload: { text: "Risultato finale" },
      }),
    ]);

    expect(text).toContain("Analisi vendite");
    expect(text).toContain("Risultato finale");
  });
});
