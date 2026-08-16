import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRuntimeSession, createRuntimeSessionWithTurn, prewarmRuntimeSession, recordRuntimeTurnClientMetrics, sendRuntimeTurn } from "./runtime";

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
    vi.mocked(fetch).mockResolvedValueOnce(
      okJson({
        session_id: "session-hot",
        workspace_id: "default",
        agent_id: "chat",
        status: "running",
        effective_mode: "sandbox",
        prewarm_status: "completed",
        prewarm_completed: true,
        provider_thread_ready: true,
      }),
    );

    const session = await createRuntimeSession({ prepare_only: true, title: "New chat" });

    expect(requestBody()).toMatchObject({
      agent_id: "chat",
      prepare_only: true,
      title: "New chat",
    });
    expect(requestBody()).not.toHaveProperty("input_text");
    expect(requestBody()).not.toHaveProperty("async");
    expect(session).toMatchObject({
      prewarm_status: "completed",
      prewarm_completed: true,
      provider_thread_ready: true,
    });
  });

  it("serializes an agentic profile choice only on the new session", async () => {
    await createRuntimeSession({
      runtime_mode: "agentic",
      workspace_profile_binding_id: "binding-codex-preview",
    });

    expect(requestBody()).toMatchObject({
      runtime_mode: "agentic",
      workspace_profile_binding_id: "binding-codex-preview",
    });
  });

  it("posts runtime session prewarm requests", async () => {
    await prewarmRuntimeSession("session-hot");

    expect(fetch).toHaveBeenCalledWith(
      "/api/runtime/sessions/session-hot/prewarm",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(requestBody()).toEqual({});
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
      clientMetrics: {
        attachment_upload_ms: 0,
        attachment_upload_ready_before_submit: true,
        attachment_upload_wait_on_submit_ms: 0,
        prepared_session_ready_before_submit: false,
        prepared_session_wait_on_submit_ms: 0,
        prepare_refs_wait_on_submit_ms: 0,
      },
    });

    expect(requestBody()).toMatchObject({
      input_text: "hello",
      client_submission_started_at: "2026-07-12T10:00:00.000Z",
      client_submission_metrics: {
        attachment_upload_ms: 0,
        attachment_upload_ready_before_submit: true,
        attachment_upload_wait_on_submit_ms: 0,
        prepared_session_ready_before_submit: false,
        prepared_session_wait_on_submit_ms: 0,
        prepare_refs_wait_on_submit_ms: 0,
      },
    });

    vi.mocked(fetch).mockClear();
    await sendRuntimeTurn("session-1", "next", "client-1", [], [], {
      clientSubmissionStartedAt: "2026-07-12T10:00:01.000Z",
      expectedRuntimeTurnId: "turn-active",
      clientMetrics: {
        prepared_session_ready_before_submit: true,
        prepared_session_wait_on_submit_ms: 0,
        prepare_refs_wait_on_submit_ms: 12.5,
      },
    });

    expect(requestBody()).toMatchObject({
      input_text: "next",
      client_message_id: "client-1",
      delivery_policy: "steer_or_queue",
      expected_runtime_turn_id: "turn-active",
      client_submission_started_at: "2026-07-12T10:00:01.000Z",
      client_submission_metrics: {
        prepared_session_ready_before_submit: true,
        prepared_session_wait_on_submit_ms: 0,
        prepare_refs_wait_on_submit_ms: 12.5,
      },
    });
  });

  it("records post-submit client metrics after the turn ack", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(okJson({ status: "recorded", turn_id: "turn-1", metric_count: 1 }));

    await recordRuntimeTurnClientMetrics("turn-1", {
      submit_post_ms: 42.25,
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/runtime/turns/turn-1/client-metrics",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(requestBody()).toMatchObject({
      metrics: {
        submit_post_ms: 42.25,
      },
    });
  });
});
