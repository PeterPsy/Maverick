import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  deleteProject,
  getSpeechCapabilities,
  prewarmSpeechWorker,
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
    await expect(synthesizeSpeech("speech", "Hello")).resolves.toMatchObject({
      audio_base64: "UklGRg==",
    });
    await expect(transcribeSpeech("speech", "UklGRg==", "audio/wav", { profile: "fast" })).resolves.toMatchObject({
      text: "Hello transcript",
    });

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/apps/speech/backend",
      "/api/apps/speech/backend",
      "/api/apps/speech/backend",
      "/api/apps/speech/backend",
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body || "{}"))).toEqual({ action: "prewarm_worker" });
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body || "{}"))).toEqual({ action: "synthesize", text: "Hello" });
    expect(JSON.parse(String(fetchMock.mock.calls[3]?.[1]?.body || "{}"))).toEqual({
      action: "transcribe_audio",
      audio_base64: "UklGRg==",
      content_type: "audio/wav",
      profile: "fast",
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

    await expect(transcribeSpeechBlob("speech", audio, { chunkIndex: 2, final: true, language: "it", profile: "fast", sessionId: "chat-session" })).resolves.toMatchObject({
      text: "Hello transcript",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe("/api/apps/speech/backend?action=transcribe_audio&language=it&profile=fast&session_id=chat-session&chunk_index=2&final=true");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ Accept: "application/json", "Content-Type": "audio/webm" });
    expect(init.body).toBe(audio);
  });
});
