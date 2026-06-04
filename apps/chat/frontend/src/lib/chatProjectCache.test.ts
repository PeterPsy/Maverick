import { afterEach, describe, expect, it, vi } from "vitest";
import { readStoredChatProjects, writeStoredChatProjects } from "./chatProjectCache";
import type { ChatProject } from "../api/client";

function project(overrides: Partial<ChatProject> = {}): ChatProject {
  return {
    project_id: "project-1",
    name: "Client",
    created_at: "2026-04-19T00:00:00.000Z",
    updated_at: "2026-04-19T00:00:01.000Z",
    ...overrides,
  };
}

function stubLocalStorage() {
  const items = new Map<string, string>();
  const localStorage = {
    clear: () => items.clear(),
    getItem: (key: string) => items.get(key) ?? null,
    key: (index: number) => Array.from(items.keys())[index] ?? null,
    removeItem: (key: string) => items.delete(key),
    setItem: (key: string, value: string) => {
      items.set(key, value);
    },
    get length() {
      return items.size;
    },
  } satisfies Storage;
  vi.stubGlobal("window", { localStorage });
  return localStorage;
}

describe("chat project cache", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps project catalogs scoped by workspace", () => {
    stubLocalStorage();

    writeStoredChatProjects("default", [project({ project_id: "default-project", name: "Default" })]);
    writeStoredChatProjects("other", [project({ project_id: "other-project", name: "Other" })]);

    expect(readStoredChatProjects("default").map((item) => item.project_id)).toEqual(["default-project"]);
    expect(readStoredChatProjects("other").map((item) => item.project_id)).toEqual(["other-project"]);
  });

  it("ignores invalid cached project entries", () => {
    const localStorage = stubLocalStorage();
    localStorage.setItem(
      "maverick.chat.projects-cache.v1:default",
      JSON.stringify({ projects: [{ project_id: "project-1", name: "Client" }, { project_id: "", name: "Broken" }, null] }),
    );

    expect(readStoredChatProjects("default")).toEqual([
      {
        project_id: "project-1",
        name: "Client",
        created_at: "",
        updated_at: "",
      },
    ]);
  });
});
