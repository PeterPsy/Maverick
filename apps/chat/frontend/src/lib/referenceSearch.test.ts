import { beforeEach, describe, expect, it, vi } from "vitest";
import { searchAppReferences, type AppEntityReference } from "../api/client";
import { searchComposerReferences } from "./referenceSearch";

vi.mock("../api/client", () => ({
  searchAppReferences: vi.fn(),
}));

const storageFolderReference: AppEntityReference = {
  type: "entity",
  app_id: "storage",
  entity_type: "folder",
  entity_id: "generated:folder%20test/",
  label: "folder test",
  summary: "Storage folder",
  deep_link: "/app/storage/folders/generated/folder%20test",
};

const storageFileReference: AppEntityReference = {
  type: "entity",
  app_id: "storage",
  entity_type: "file",
  entity_id: "uploaded:logo.svg",
  label: "logo.svg",
  summary: "Storage file",
  deep_link: "/app/storage/files/uploaded/logo.svg",
};

const checklistReference: AppEntityReference = {
  type: "entity",
  app_id: "checklist",
  entity_type: "checklist",
  entity_id: "check_123",
  label: "Launch checklist",
  summary: "Checklist",
  deep_link: "/app/checklist/checklists/check_123",
};

const mockedSearchAppReferences = vi.mocked(searchAppReferences);

describe("searchComposerReferences", () => {
  beforeEach(() => {
    mockedSearchAppReferences.mockReset();
  });

  it("prioritizes generic file and folder references without an active app context", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences
      .mockResolvedValueOnce([storageFolderReference, storageFileReference])
      .mockResolvedValueOnce([checklistReference, storageFolderReference]);

    const references = await searchComposerReferences("", signal, "");

    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(1, "", signal, { entityTypes: ["file", "folder"], limit: 16 });
    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(2, "", signal, { limit: 16 });
    expect(references).toEqual([storageFolderReference, storageFileReference, checklistReference]);
  });

  it("returns active app results without waiting for the global fallback", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences.mockResolvedValueOnce([checklistReference]);

    const references = await searchComposerReferences("speech", signal, "checklist");

    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(1, "speech", signal, { appIds: ["checklist"], limit: 16 });
    expect(mockedSearchAppReferences).toHaveBeenCalledTimes(1);
    expect(references).toEqual([checklistReference]);
  });

  it("uses a checklist entity search for checklist category queries", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences.mockResolvedValueOnce([checklistReference]);

    const references = await searchComposerReferences("checklists", signal, "");

    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(1, "checklists", signal, {
      entityTypes: ["checklist"],
      limit: 16,
    });
    expect(mockedSearchAppReferences).toHaveBeenCalledTimes(1);
    expect(references).toEqual([checklistReference]);
  });

  it("falls back to global search when targeted searches do not find references", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([storageFolderReference])
      .mockResolvedValueOnce([checklistReference, storageFolderReference]);

    const references = await searchComposerReferences("folders", signal, "");

    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(1, "folders", signal, { entityTypes: ["file", "folder"], limit: 16 });
    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(2, "folders", signal, { entityTypes: ["file", "folder"], limit: 16 });
    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(3, "folders", signal, { limit: 16 });
    expect(references).toEqual([storageFolderReference, checklistReference]);
  });
});
