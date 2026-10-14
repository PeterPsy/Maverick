import { describe, expect, it } from "vitest";
import { storageSelectionFromParams } from "./storageSelection";

describe("storageSelectionFromParams", () => {
  it("returns a verified local Storage selection", () => {
    expect(
      storageSelectionFromParams({
        picker_mode: "workspace-file",
        picker_context: "work-1",
        storage_picker_result: JSON.stringify({
          file: {
            workspace_relative_path: "storage/uploaded/brief.pdf",
          },
        }),
      }),
    ).toEqual({
      workId: "work-1",
      workspaceRelativePath: "storage/uploaded/brief.pdf",
      requestKey: "storage:work-1:storage/uploaded/brief.pdf",
    });
  });

  it("rejects malformed and remote selections", () => {
    expect(
      storageSelectionFromParams({
        picker_mode: "workspace-file",
        picker_context: "work-1",
        storage_picker_result: "not-json",
      }),
    ).toBeNull();
    expect(
      storageSelectionFromParams({
        picker_mode: "workspace-file",
        picker_context: "work-1",
        storage_picker_result: JSON.stringify({
          file: { workspace_relative_path: "drive/file.pdf" },
        }),
      }),
    ).toBeNull();
  });
});
