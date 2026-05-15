import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, deleteProject, selectedDependencyProviderAppId, type AppDependenciesPayload } from "./client";

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

function dependencyPayload(selectedProviderAppIds: string[]): AppDependenciesPayload {
  return {
    workspace_id: "default",
    consumer_app_id: "chat",
    status: "resolved",
    dependencies: [
      {
        alias: "agent-catalog",
        interface: "agent.catalog",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Agent catalog",
        status: selectedProviderAppIds.length ? "resolved" : "optional_unset",
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
    ],
  };
}

describe("Chat API dependency helpers", () => {
  it("uses the explicit dependency provider or the first available catalog", () => {
    expect(selectedDependencyProviderAppId(dependencyPayload(["agents"]), "agent-catalog")).toBe("agents");
    expect(selectedDependencyProviderAppId(dependencyPayload([]), "agent-catalog")).toBe("agents");
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
