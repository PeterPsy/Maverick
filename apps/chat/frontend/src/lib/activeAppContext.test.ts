import { describe, expect, it } from "vitest";
import {
  activeAppContextFromWidgetContext,
  mergeAppReferences,
  mergeSelectedReferenceMentionItems,
  promptWithActiveAppContext,
  referenceMentionItem,
} from "./activeAppContext";

const activeApp = {
  app_id: "storage",
  description: "Workspace files",
  name: "Storage",
  views: ["sidebar"],
};

describe("active app context helpers", () => {
  it("extracts the shell active app from widget context payloads", () => {
    expect(
      activeAppContextFromWidgetContext({
        content: {
          payload: {
            active_app: {
              app_id: " storage ",
              description: "Workspace files",
              name: " Storage ",
              views: ["sidebar", 42],
            },
          },
        },
      }),
    ).toEqual(activeApp);
  });

  it("ignores missing context and chat itself", () => {
    expect(activeAppContextFromWidgetContext({})).toBeNull();
    expect(
      activeAppContextFromWidgetContext({
        content: { payload: { active_app: { app_id: "chat", name: "Chat" } } },
      }),
    ).toBeNull();
  });

  it("preserves scalar active app params for contextual source-app chat", () => {
    expect(
      activeAppContextFromWidgetContext({
        content: {
          payload: {
            active_app: {
              app_id: "design-studio",
              name: "Design Studio",
              params: { od_project_id: "od_project_1", nested: { blocked: true } },
            },
          },
        },
      }),
    ).toMatchObject({ app_id: "design-studio", params: { od_project_id: "od_project_1" } });
  });

  it("adds active app context to prompts once", () => {
    const prompted = promptWithActiveAppContext("Base prompt", activeApp);

    expect(prompted).toContain("Base prompt");
    expect(prompted).toContain("- active_app_id: storage");
    expect(promptWithActiveAppContext(prompted, activeApp)).toBe(prompted);
  });

  it("merges active app references without duplicates", () => {
    expect(mergeAppReferences([], activeApp)).toEqual([{ type: "app", app_id: "storage", label: "Storage" }]);
    expect(mergeAppReferences([{ type: "app", app_id: "storage", label: "Files" }], activeApp)).toEqual([
      { type: "app", app_id: "storage", label: "Files" },
    ]);
  });

  it("turns selected app and entity references into mention items", () => {
    const selectedReferences = [
      { type: "app" as const, app_id: "storage", label: "Storage" },
      {
        type: "entity" as const,
        app_id: "storage",
        entity_type: "file",
        entity_id: "file-1",
        label: "report.md",
        summary: "Report",
      },
    ];

    expect(referenceMentionItem(selectedReferences[0])).toMatchObject({ id: "storage", kind: "app", label: "Storage" });
    expect(mergeSelectedReferenceMentionItems([], selectedReferences).map((item) => item.id)).toEqual([
      "storage",
      "entity:storage:file:file-1",
    ]);
  });
});
