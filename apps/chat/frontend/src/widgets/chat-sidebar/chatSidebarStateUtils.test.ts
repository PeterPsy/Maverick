import { describe, expect, it, vi } from "vitest";
import { updateFromSidebarPayload } from "./chatSidebarStateUtils";


describe("updateFromSidebarPayload", () => {
  it("preserves the loaded project catalog when a thread-only delta omits projects", () => {
    const setProjects = vi.fn();

    updateFromSidebarPayload({}, setProjects);

    expect(setProjects).not.toHaveBeenCalled();
  });

  it("applies an explicitly returned project catalog", () => {
    const setProjects = vi.fn();
    const projects = [
      {
        project_id: "project-1",
        name: "Project",
        created_at: "2026-08-19T00:00:00.000Z",
        updated_at: "2026-08-19T00:00:00.000Z",
      },
    ];

    updateFromSidebarPayload({ projects }, setProjects);

    expect(setProjects).toHaveBeenCalledWith(projects);
  });
});
