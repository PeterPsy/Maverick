import { afterEach, describe, expect, it, vi } from "vitest";
import { sendSourceAppTurn } from "./sourceAppChat";

function okJson(payload: unknown): Response {
  return { ok: true, status: 200, json: async () => payload } as Response;
}

describe("source app chat bridge", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("submits through the owning app and hydrates the generic Chat response", async () => {
    const responses = [
      {
        runtime_request_results: [
          { status: "submitted", runtime_session_id: "session-design", turn_id: "turn-design" },
        ],
      },
      { session_id: "session-design", workspace_id: "default", agent_id: "chat", status: "running", effective_mode: "sandbox" },
      {
        turn_id: "turn-design",
        session_id: "session-design",
        workspace_id: "default",
        status: "queued",
        input_text: "Create a landing page",
        failure_reason: null,
        created_at: "2026-08-10T00:00:00Z",
        updated_at: "2026-08-10T00:00:00Z",
      },
      {
        thread: {
          thread_id: "session-design",
          runtime_session_id: "session-design",
          title: "Landing page",
          agent_label: "Maverick Design Runtime",
          agent_type_id: "chat",
          agent_role_id: "",
          source_app_id: "design-studio",
          system_prompt: "",
          project_id: "od_project_1",
          archived: false,
          availability: "queued",
          created_at: "2026-08-10T00:00:00Z",
          updated_at: "2026-08-10T00:00:00Z",
          last_user_message_at: "2026-08-10T00:00:00Z",
        },
      },
      { items: [] },
    ];
    vi.stubGlobal("fetch", vi.fn(async () => okJson(responses.shift())));

    const result = await sendSourceAppTurn({
      appReferences: [],
      attachments: [],
      clientMessageId: "client-1",
      inputText: "Create a landing page",
      invokedSkillIds: ["storage-ops"],
      mode: "design",
      projectId: "od_project_1",
      sourceAppId: "design-studio",
    });

    expect(result.thread?.source_app_id).toBe("design-studio");
    expect(result.turn?.turn_id).toBe("turn-design");
    const firstBody = JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body));
    expect(firstBody).toMatchObject({
      action: "chat.submit_turn",
      arguments: {
        invoked_skill_ids: ["storage-ops"],
        project_id: "od_project_1",
        session_mode: "design",
      },
    });
    expect(vi.mocked(fetch).mock.calls.map((call) => call[0])).toEqual([
      "/api/apps/design-studio/backend",
      "/api/runtime/sessions/session-design",
      "/api/runtime/turns/turn-design",
      "/api/runtime/threads/session-design",
      "/api/runtime/sessions/session-design/events?limit=500",
    ]);
  });
});
