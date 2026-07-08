import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  closeInterAgentRun,
  createInterAgentRun,
  deleteProject,
  executeInterAgentRun,
  getInterAgentRun,
  getRuntimeThread,
  getSpeechCapabilities,
  interruptInterAgentRun,
  listInterAgentRunArtifacts,
  listInterAgentRunApprovals,
  listInterAgentRunEvents,
  listInterAgentRuns,
  listRuntimeSessionEvents,
  listRuntimeThreads,
  prewarmSpeechWorker,
  resolveInterAgentApproval,
  resumeInterAgentRun,
  selectedDependencyProviderAppId,
  selectedSharedDependencyProviderAppId,
  synthesizeSpeech,
  transcribeSpeech,
  transcribeSpeechBlob,
  type AppDependenciesPayload,
} from "./client";

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

function dependencyPayload(selectedProviderAppIds: string[]): AppDependenciesPayload {
  const status = selectedProviderAppIds.length ? "resolved" : "optional_unset";
  return {
    workspace_id: "default",
    consumer_app_id: "chat",
    status,
    dependencies: [
      {
        alias: "agent-catalog",
        interface: "agent.catalog",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Agent catalog",
        status,
        candidates: [
          {
            app_id: "agents",
            name: "Agents",
            version: "0.1.0",
            interface: "agent.catalog",
            interface_version: "1",
            description: "Agent catalog",
            surfaces: ["backend"],
          },
        ],
        selected_provider_app_ids: selectedProviderAppIds,
        stale_provider_app_ids: [],
        blocked_reason: null,
      },
      {
        alias: "agent-prompt-materializer",
        interface: "agent.prompt-materializer",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Agent prompt materializer",
        status,
        candidates: [
          {
            app_id: "agents",
            name: "Agents",
            version: "0.1.0",
            interface: "agent.prompt-materializer",
            interface_version: "1",
            description: "Agent prompt materializer",
            surfaces: ["backend"],
          },
        ],
        selected_provider_app_ids: selectedProviderAppIds,
        stale_provider_app_ids: [],
        blocked_reason: null,
      },
    ],
  };
}

describe("Chat API dependency helpers", () => {
  it("uses explicit dependency providers only for single dependency consumers", () => {
    expect(selectedDependencyProviderAppId(dependencyPayload(["agents"]), "agent-catalog")).toBe("agents");
    expect(selectedDependencyProviderAppId(dependencyPayload([]), "agent-catalog")).toBe("");
  });

  it("does not fall back when the dependency is stale", () => {
    const payload = dependencyPayload([]);
    payload.dependencies[0].status = "stale";
    payload.dependencies[0].stale_provider_app_ids = ["agents-old"];

    expect(selectedDependencyProviderAppId(payload, "agent-catalog")).toBe("");
  });

  it("uses only backend-capable dependency providers", () => {
    const payload = dependencyPayload(["agents"]);
    payload.dependencies[0].candidates[0].surfaces = ["cli"];

    expect(selectedDependencyProviderAppId(payload, "agent-catalog")).toBe("");
  });

  it("uses one provider only when catalog and prompt materializer both resolve", () => {
    expect(selectedSharedDependencyProviderAppId(dependencyPayload(["agents"]), ["agent-catalog", "agent-prompt-materializer"])).toBe("agents");
    expect(selectedSharedDependencyProviderAppId(dependencyPayload([]), ["agent-catalog", "agent-prompt-materializer"])).toBe("agents");

    const payload = dependencyPayload([]);
    payload.dependencies[1].status = "missing_provider";
    payload.dependencies[1].candidates = [];
    payload.dependencies[1].blocked_reason = "No prompt materializer.";

    expect(selectedSharedDependencyProviderAppId(payload, ["agent-catalog", "agent-prompt-materializer"])).toBe("");
  });
});

describe("deleteProject", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rejects incomplete delete responses so the sidebar does not clear every project", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ project_id: "project-1" })));

    await expect(deleteProject("project-1")).rejects.toMatchObject({
      name: "ApiError",
      message: "Project deletion did not return updated projects.",
      path: "/api/apps/chat/backend",
      status: 502,
    } satisfies Partial<ApiError>);
  });

  it("accepts an explicit empty project list from a completed delete", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ projects: [], preferences: { view: "all" } })));

    await expect(deleteProject("project-1")).resolves.toEqual({
      projects: [],
      preferences: { view: "all" },
    });
  });
});

describe("runtime event client calls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads bounded runtime events for sidebar transcript search", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [{ event_id: "event-1" }] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listRuntimeSessionEvents("session/1", { limit: 25 })).resolves.toEqual({ items: [{ event_id: "event-1" }] });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/runtime/sessions/session%2F1/events?limit=25",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    );
  });

  it("loads bounded runtime thread search results", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ threads: [], threads_page: { limit: 50, has_more: false, cursor: null, sort: "recency_desc", query: "archive thread" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listRuntimeThreads({ query: "archive thread", limit: 50 })).resolves.toEqual({
      threads: [],
      threads_page: { limit: 50, has_more: false, cursor: null, sort: "recency_desc", query: "archive thread" },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/runtime/threads?query=archive+thread&limit=50",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    );
  });

  it("passes runtime thread page cursors", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ threads: [], threads_page: { limit: 50, has_more: false, cursor: null, sort: "recency_desc", cursor_found: true } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(listRuntimeThreads({ cursor: "thread-50", limit: 50 })).resolves.toEqual({
      threads: [],
      threads_page: { limit: 50, has_more: false, cursor: null, sort: "recency_desc", cursor_found: true },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/runtime/threads?cursor=thread-50&limit=50",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    );
  });

  it("loads one runtime thread detail by id", async () => {
    const thread = { thread_id: "thread/1", runtime_session_id: "session-1" };
    const fetchMock = vi.fn(async () => jsonResponse({ thread }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getRuntimeThread("thread/1")).resolves.toEqual(thread);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/runtime/threads/thread%2F1",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    );
  });
});

describe("inter-agent client calls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls core-owned inter-agent HTTP surfaces", async () => {
    const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/inter-agent/runs" && !init?.method) {
        return jsonResponse({ items: [] });
      }
      if (path === "/api/inter-agent/runs" && init?.method === "POST") {
        return jsonResponse({ run: { run_id: "run-1" }, participants: [] }, 201);
      }
      if (path === "/api/inter-agent/runs/run-1" && !init?.method) {
        return jsonResponse({ run: { run_id: "run-1", status: "created" }, participants: [] });
      }
      if (path === "/api/inter-agent/runs/run-1/execute") {
        return jsonResponse({ run: { run_id: "run-1", status: "completed" }, participants: [], root_runtime_events: [] });
      }
      if (path === "/api/inter-agent/runs/run-1/events?visibility_plane=summary&limit=10") {
        return jsonResponse({ items: [] });
      }
      if (path === "/api/inter-agent/runs/run-1/artifacts?visibility_plane=detail&limit=10") {
        return jsonResponse({ items: [{ artifact_id: "artifact-1", label: "Report" }] });
      }
      if (path === "/api/inter-agent/runs/run-1/approvals") {
        return jsonResponse({ items: [] });
      }
      if (path === "/api/inter-agent/approvals/approval-1/resolve") {
        return jsonResponse({ approval: { approval_id: "approval-1", status: "approved" } });
      }
      if (path === "/api/inter-agent/runs/run-1/interrupt") {
        return jsonResponse({ run: { run_id: "run-1", status: "paused" } });
      }
      if (path === "/api/inter-agent/runs/run-1/resume") {
        return jsonResponse({ run: { run_id: "run-1", status: "running" }, participants: [] });
      }
      if (path === "/api/inter-agent/runs/run-1/close") {
        return jsonResponse({ run: { run_id: "run-1", status: "cancelled" }, participant_cleanups: [] });
      }
      return jsonResponse({ error: "unexpected" }, 500);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(listInterAgentRuns()).resolves.toEqual({ items: [] });
    await expect(
      createInterAgentRun({
        thread_id: "thread-1",
        root_runtime_session_id: "session-1",
        mode: "manager_tools",
        idempotency_key: "key-1",
        participants: [
          { participant_id: "orchestrator", kind: "orchestrator", execution_mode: "root_orchestrator", label: "Orchestrator" },
          { participant_id: "assistant", kind: "agent", execution_mode: "child_runtime_session", label: "Assistant" },
        ],
        budget: {
          max_participants: 2,
          max_concurrent_participants: 1,
          max_total_turns: 2,
          max_turns_per_participant: 1,
          max_tool_calls: 1,
        },
      }),
    ).resolves.toMatchObject({ run: { run_id: "run-1" } });
    await expect(getInterAgentRun("run-1")).resolves.toMatchObject({ run: { run_id: "run-1", status: "created" } });
    await expect(
      executeInterAgentRun("run-1", {
        input_text: "Plan",
        client_message_id: "client-1",
        participant_inputs: { implementer: "Implement", reviewer: "Review" },
        async: true,
        attachments: [{ id: "att-1", name: "brief.md", size: 12, type: "text/markdown", isImage: false, objectUrl: "blob:http://local/att-1" }],
      }),
    ).resolves.toMatchObject({
      run: { status: "completed" },
    });
    await expect(listInterAgentRunEvents("run-1", { visibilityPlane: "summary", limit: 10 })).resolves.toEqual({ items: [] });
    await expect(listInterAgentRunArtifacts("run-1", { visibilityPlane: "detail", limit: 10 })).resolves.toEqual({
      items: [{ artifact_id: "artifact-1", label: "Report" }],
    });
    await expect(listInterAgentRunApprovals("run-1")).resolves.toEqual({ items: [] });
    await expect(resolveInterAgentApproval("approval-1", { approved: true })).resolves.toMatchObject({
      approval: { status: "approved" },
    });
    await expect(interruptInterAgentRun("run-1", { reason: "pause" })).resolves.toMatchObject({ run: { status: "paused" } });
    await expect(resumeInterAgentRun("run-1", { reason: "resume" })).resolves.toMatchObject({ run: { status: "running" } });
    await expect(closeInterAgentRun("run-1", { reason: "stop", terminal_status: "cancelled" })).resolves.toMatchObject({
      run: { status: "cancelled" },
    });

    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body || "{}"))).toMatchObject({
      root_runtime_session_id: "session-1",
      mode: "manager_tools",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[3]?.[1]?.body || "{}"))).toMatchObject({
      input_text: "Plan",
      client_message_id: "client-1",
      participant_inputs: { implementer: "Implement", reviewer: "Review" },
      async: true,
      attachments: [{ id: "att-1", name: "brief.md" }],
    });
    expect(JSON.parse(String(fetchMock.mock.calls[3]?.[1]?.body || "{}")).attachments[0]).not.toHaveProperty("objectUrl");
    expect(JSON.parse(String(fetchMock.mock.calls.at(-3)?.[1]?.body || "{}"))).toEqual({ reason: "pause" });
    expect(JSON.parse(String(fetchMock.mock.calls.at(-2)?.[1]?.body || "{}"))).toEqual({ reason: "resume" });
    expect(JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body || "{}"))).toEqual({ reason: "stop", terminal_status: "cancelled" });
  });
});

describe("speech provider client calls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the selected provider backend for capabilities, prewarm, synthesis, and transcription", async () => {
    const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body || "{}"));
      if (body.action === "capabilities") {
        return jsonResponse({
          interfaces: {
            "speech.synthesis": { available: true, provider_available: true },
            "speech.transcription": { available: true, provider_available: true },
          },
        });
      }
      if (body.action === "transcribe_audio") {
        return jsonResponse({ text: "Hello transcript", retention: "metadata_only" });
      }
      return jsonResponse({ audio_base64: "UklGRg==", content_type: "audio/wav" });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getSpeechCapabilities("speech")).resolves.toMatchObject({
      interfaces: { "speech.synthesis": { available: true } },
    });
    await expect(prewarmSpeechWorker("speech")).resolves.toMatchObject({});
    await expect(synthesizeSpeech("speech", "Hello", { language: "it" })).resolves.toMatchObject({
      audio_base64: "UklGRg==",
    });
    await expect(transcribeSpeech("speech", "UklGRg==", "audio/wav", { profile: "fast" })).resolves.toMatchObject({
      text: "Hello transcript",
    });
    await expect(transcribeSpeech("speech", "UklGRg==", "audio/wav", { conversation: true, sessionId: "voice-session" })).resolves.toMatchObject({
      text: "Hello transcript",
    });

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/apps/speech/backend",
      "/api/apps/speech/backend",
      "/api/apps/speech/backend",
      "/api/apps/speech/backend",
      "/api/apps/speech/backend",
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body || "{}"))).toEqual({ action: "prewarm_worker" });
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body || "{}"))).toEqual({ action: "synthesize", text: "Hello", language: "it" });
    expect(JSON.parse(String(fetchMock.mock.calls[3]?.[1]?.body || "{}"))).toEqual({
      action: "transcribe_audio",
      audio_base64: "UklGRg==",
      content_type: "audio/wav",
      profile: "fast",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body || "{}"))).toEqual({
      action: "transcribe_audio",
      audio_base64: "UklGRg==",
      content_type: "audio/wav",
      conversation: "true",
      session_id: "voice-session",
    });
  });

  it("prefers backend detail text for failed speech requests", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ error: "transcription_failed", detail: "language en-us is unsupported" }, 502)));

    await expect(transcribeSpeech("speech", "UklGRg==", "audio/webm", "en-us")).rejects.toMatchObject({
      name: "ApiError",
      message: "language en-us is unsupported",
      status: 502,
    } satisfies Partial<ApiError>);
  });

  it("sends dictation audio as a binary backend request", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ text: "Hello transcript", retention: "metadata_only" }));
    vi.stubGlobal("fetch", fetchMock);
    const audio = new Blob(["audio"], { type: "audio/webm" });

    await expect(
      transcribeSpeechBlob("speech", audio, { chunkIndex: 2, dictation: true, final: true, language: "it", profile: "fast", sessionId: "chat-session" }),
    ).resolves.toMatchObject({
      text: "Hello transcript",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe(
      "/api/apps/speech/backend?action=transcribe_audio&language=it&profile=fast&session_id=chat-session&chunk_index=2&final=true&dictation=true",
    );
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ Accept: "application/json", "Content-Type": "audio/webm" });
    expect(init.body).toBe(audio);
  });
});
