import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRuntimeSession, createRuntimeSessionWithTurn, sendRuntimeTurn } from "./runtime";

function okJson(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  } as Response;
}

function requestBody(callIndex = 0): Record<string, unknown> {
  const init = vi.mocked(fetch).mock.calls[callIndex]?.[1] as RequestInit | undefined;
  return JSON.parse(String(init?.body || "{}")) as Record<string, unknown>;
}

describe("runtime API client", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        okJson({
          session_id: "session-1",
          workspace_id: "default",
          agent_id: "chat",
          status: "running",
          effective_mode: "sandbox",
          runtime_mode: "agentic",
        }),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps runtime mode out of default Chat session requests", async () => {
    await createRuntimeSession();

    expect(fetch).toHaveBeenCalledWith(
      "/api/runtime/sessions",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(requestBody()).not.toHaveProperty("runtime_mode");
    expect(requestBody()).not.toHaveProperty("routing_profile");
  });

  it("serializes prepared session creation without a turn", async () => {
    await createRuntimeSession({ prepare_only: true, title: "New chat" });

    expect(requestBody()).toMatchObject({
      agent_id: "chat",
      prepare_only: true,
      title: "New chat",
    });
    expect(requestBody()).not.toHaveProperty("input_text");
    expect(requestBody()).not.toHaveProperty("async");
  });

  it("serializes plain hosted Chat session options for runtime creation with a turn", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      okJson({
        session: {
          session_id: "session-plain",
          workspace_id: "default",
          agent_id: "chat",
          status: "running",
          effective_mode: "sandbox",
          runtime_mode: "plain_hosted_chat",
          provider_id: "hosted-text-runtime",
        },
        turn: {
          turn_id: "turn-plain",
          session_id: "session-plain",
          workspace_id: "default",
          status: "queued",
          input_text: "hello",
          failure_reason: null,
          runtime_mode: "plain_hosted_chat",
          created_at: "2026-06-22T00:00:00Z",
          updated_at: "2026-06-22T00:00:00Z",
        },
        events: [],
      }),
    );

    await createRuntimeSessionWithTurn({
      inputText: "hello",
      options: {
        runtime_mode: "plain_hosted_chat",
        routing_profile: "fast_model",
        hosted_provider_id: "openrouter",
        hosted_model_id: "google/gemma-4-31b-it:free",
      },
    });

    expect(requestBody()).toMatchObject({
      agent_id: "chat",
      input_text: "hello",
      runtime_mode: "plain_hosted_chat",
      routing_profile: "fast_model",
      hosted_provider_id: "openrouter",
      hosted_model_id: "google/gemma-4-31b-it:free",
      async: true,
    });
  });

  it("serializes client submission timing for turn creation", async () => {
    await createRuntimeSessionWithTurn({
      inputText: "hello",
      clientSubmissionStartedAt: "2026-07-12T10:00:00.000Z",
    });

    expect(requestBody()).toMatchObject({
      input_text: "hello",
      client_submission_started_at: "2026-07-12T10:00:00.000Z",
    });

    vi.mocked(fetch).mockClear();
    await sendRuntimeTurn("session-1", "next", "client-1", [], [], {
      clientSubmissionStartedAt: "2026-07-12T10:00:01.000Z",
    });

    expect(requestBody()).toMatchObject({
      input_text: "next",
      client_message_id: "client-1",
      client_submission_started_at: "2026-07-12T10:00:01.000Z",
    });
  });
});
