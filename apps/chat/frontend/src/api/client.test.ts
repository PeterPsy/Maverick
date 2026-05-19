import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  deleteProject,
  getSpeechCapabilities,
  selectedDependencyProviderAppId,
  selectedSharedDependencyProviderAppId,
  synthesizeSpeech,
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
  it("uses the explicit dependency provider or the first available catalog", () => {
    expect(selectedDependencyProviderAppId(dependencyPayload(["agents"]), "agent-catalog")).toBe("agents");
    expect(selectedDependencyProviderAppId(dependencyPayload([]), "agent-catalog")).toBe("agents");
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

  it("calls the selected provider backend for capabilities and synthesis", async () => {
    const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body || "{}"));
      if (body.action === "capabilities") {
        return jsonResponse({ interfaces: { "speech.synthesis": { available: true, provider_available: true } } });
      }
      return jsonResponse({ audio_base64: "UklGRg==", content_type: "audio/wav" });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getSpeechCapabilities("speech")).resolves.toMatchObject({
      interfaces: { "speech.synthesis": { available: true } },
    });
    await expect(synthesizeSpeech("speech", "Hello")).resolves.toMatchObject({
      audio_base64: "UklGRg==",
    });

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(["/api/apps/speech/backend", "/api/apps/speech/backend"]);
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body || "{}"))).toEqual({ action: "synthesize", text: "Hello" });
  });
});
