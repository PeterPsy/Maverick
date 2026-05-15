import { describe, expect, it } from "vitest";
import { storageAppPageShellHref, storageLinkTargetFromHref, storageShellHref, workspaceStoragePathFromTarget } from "./storageLinks";

describe("storage link helpers", () => {
  it("normalizes workspace storage paths from relative links", () => {
    expect(workspaceStoragePathFromTarget("storage/generated/report.md")).toBe("storage/generated/report.md");
    expect(workspaceStoragePathFromTarget("storage/uploaded/uploads/logo.svg")).toBe("storage/uploaded/uploads/logo.svg");
  });

  it("normalizes absolute filesystem links without exposing host roots", () => {
    expect(
      workspaceStoragePathFromTarget(
        "/home/ubuntu/projects/maverick-v3/workspaces/default/storage/generated/agents-cli-mcp-speed-report.md:1",
      ),
    ).toBe("storage/generated/agents-cli-mcp-speed-report.md");
  });

  it("normalizes hosted workspace storage URLs", () => {
    expect(workspaceStoragePathFromTarget("https://maverick.test/workspaces/default/storage/generated/final%20report.pdf")).toBe(
      "storage/generated/final report.pdf",
    );
  });

  it("rejects non-storage and traversal links", () => {
    expect(workspaceStoragePathFromTarget("/home/ubuntu/projects/maverick-v3/workspaces/default/tmp/report.md")).toBe("");
    expect(workspaceStoragePathFromTarget("storage/generated/../secret.md")).toBe("");
  });

  it("builds canonical shell hrefs for storage paths", () => {
    expect(storageShellHref("storage/generated/final report.pdf")).toBe(
      "/app/storage?workspace_relative_path=storage%2Fgenerated%2Ffinal+report.pdf",
    );
  });

  it("recognizes Storage app deep links", () => {
    expect(storageLinkTargetFromHref("/app/storage/files/file_123")).toEqual({
      kind: "app_page",
      appPage: "files/file_123",
    });
    expect(storageLinkTargetFromHref("/app/storage?workspace_relative_path=storage%2Fgenerated%2Freport.md")).toEqual({
      kind: "workspace_path",
      workspaceRelativePath: "storage/generated/report.md",
    });
  });

  it("builds canonical shell hrefs for Storage app pages", () => {
    expect(storageAppPageShellHref("folders/generated/Client Docs")).toBe("/app/storage/folders/generated/Client%20Docs");
  });
});
