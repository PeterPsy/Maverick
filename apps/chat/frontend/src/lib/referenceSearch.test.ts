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

const clientStorageReference: AppEntityReference = {
  type: "entity",
  app_id: "storage",
  entity_type: "file",
  entity_id: "generated:client-plan.pdf",
  label: "Client plan.pdf",
  summary: "PDF file at storage/generated/Client plan.pdf",
  deep_link: "/app/storage/files/generated/client-plan.pdf",
};

const clientChecklistReference: AppEntityReference = {
  type: "entity",
  app_id: "checklist",
  entity_type: "checklist",
  entity_id: "check_client",
  label: "Client checklist",
  summary: "Checklist",
  deep_link: "/app/checklist/checklists/check_client",
};

const mockedSearchAppReferences = vi.mocked(searchAppReferences);

function genericChecklistReference(index: number): AppEntityReference {
  return {
    type: "entity",
    app_id: "checklist",
    entity_type: "checklist",
    entity_id: `check_${index}`,
    label: `Generic checklist result ${index}`,
    summary: "Checklist",
    deep_link: `/app/checklist/checklists/check_${index}`,
  };
}

describe("searchComposerReferences", () => {
  beforeEach(() => {
    mockedSearchAppReferences.mockReset();
    mockedSearchAppReferences.mockResolvedValue([]);
  });

  it("uses generic file and folder references for an empty picker without an active app context", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences.mockResolvedValueOnce([storageFolderReference, storageFileReference]);

    const references = await searchComposerReferences("", signal, "");

    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(1, "", signal, { entityTypes: ["file", "folder"], limit: 16 });
    expect(mockedSearchAppReferences).toHaveBeenCalledTimes(1);
    expect(references).toEqual([storageFolderReference, storageFileReference]);
  });

  it("searches the active app and Storage together before the global fallback", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences.mockResolvedValueOnce([checklistReference]);

    const references = await searchComposerReferences("speech", signal, "checklist");

    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(1, "speech", signal, { appIds: ["checklist"], limit: 16 });
    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(2, "speech", signal, {
      appIds: ["storage"],
      entityTypes: ["file", "folder"],
      limit: 16,
    });
    expect(mockedSearchAppReferences).toHaveBeenCalledTimes(2);
    expect(references).toEqual([checklistReference]);
  });

  it("keeps an exact Storage filename match ahead of noisy active app results", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences
      .mockResolvedValueOnce(Array.from({ length: 16 }, (_item, index) => genericChecklistReference(index + 1)))
      .mockResolvedValueOnce([storageFileReference]);

    const references = await searchComposerReferences("logo.svg", signal, "checklist");

    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(1, "logo.svg", signal, { appIds: ["checklist"], limit: 16 });
    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(2, "logo.svg", signal, {
      appIds: ["storage"],
      entityTypes: ["file", "folder"],
      limit: 16,
    });
    expect(references[0]).toEqual(storageFileReference);
    expect(references.some((reference) => reference.app_id === "checklist")).toBe(true);
  });

  it("uses a checklist entity search for checklist category queries", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences.mockResolvedValueOnce([]).mockResolvedValueOnce([checklistReference]);

    const references = await searchComposerReferences("checklists", signal, "");

    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(1, "checklists", signal, {
      appIds: ["storage"],
      entityTypes: ["file", "folder"],
      limit: 16,
    });
    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(2, "checklists", signal, {
      entityTypes: ["checklist"],
      limit: 16,
    });
    expect(mockedSearchAppReferences).toHaveBeenCalledTimes(2);
    expect(references).toEqual([checklistReference]);
  });

  it("falls back to global search when targeted searches do not find references", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([checklistReference, storageFolderReference]);

    const references = await searchComposerReferences("folders", signal, "");

    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(1, "folders", signal, {
      appIds: ["storage"],
      entityTypes: ["file", "folder"],
      limit: 16,
    });
    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(2, "folders", signal, { limit: 16 });
    expect(references).toEqual([storageFolderReference, checklistReference]);
  });

  it("fills generic searches from the global fallback after the Storage-first batch", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences
      .mockResolvedValueOnce([clientStorageReference])
      .mockResolvedValueOnce([clientChecklistReference]);

    const references = await searchComposerReferences("client", signal, "");

    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(1, "client", signal, {
      appIds: ["storage"],
      entityTypes: ["file", "folder"],
      limit: 16,
    });
    expect(mockedSearchAppReferences).toHaveBeenNthCalledWith(2, "client", signal, { limit: 16 });
    expect(references).toEqual([clientStorageReference, clientChecklistReference]);
  });

  it("uses a short composer cache for repeated query and active app searches", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences.mockResolvedValueOnce([checklistReference]);

    const first = await searchComposerReferences("cached query", signal, "checklist", "default");
    const second = await searchComposerReferences("cached query", signal, "checklist", "default");

    expect(mockedSearchAppReferences).toHaveBeenCalledTimes(2);
    expect(first).toEqual([checklistReference]);
    expect(second).toEqual([checklistReference]);
  });

  it("keeps composer cache entries scoped by workspace", async () => {
    const signal = new AbortController().signal;
    mockedSearchAppReferences
      .mockResolvedValueOnce([checklistReference])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([storageFileReference]);

    const first = await searchComposerReferences("workspace scoped query", signal, "checklist", "default");
    const second = await searchComposerReferences("workspace scoped query", signal, "checklist", "other-workspace");

    expect(mockedSearchAppReferences).toHaveBeenCalledTimes(4);
    expect(first).toEqual([checklistReference]);
    expect(second).toEqual([storageFileReference]);
  });
});
