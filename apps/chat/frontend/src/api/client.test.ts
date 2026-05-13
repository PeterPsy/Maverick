import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, deleteProject } from "./client";

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

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
