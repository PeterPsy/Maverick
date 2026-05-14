import { describe, expect, it } from "vitest";
import { hasStorageReferenceDragData, storageReferenceMentionItemsFromDataTransfer } from "./storageDragReferences";

class FakeDataTransfer {
  types: string[] = [];
  private readonly data = new Map<string, string>();

  getData(type: string) {
    return this.data.get(type.toLowerCase()) || "";
  }

  setData(type: string, value: string) {
    const normalizedType = type.toLowerCase();
    this.data.set(normalizedType, value);
    if (!this.types.includes(normalizedType)) {
      this.types.push(normalizedType);
    }
  }
}

function storageSelectionTransfer() {
  const dataTransfer = new FakeDataTransfer();
  dataTransfer.setData(
    "application/x-maverick-storage-selection",
    JSON.stringify({
      owner_app_id: "storage",
      files: [
        {
          file_id: "file_123",
          name: "report.md",
          owner_app_id: "storage",
          relative_path: "Reports/report.md",
          role: "generated",
          workspace_relative_path: "storage/generated/Reports/report.md",
        },
      ],
      folders: [
        {
          folder_id: "generated:Client Docs/",
          name: "Client Docs",
          owner_app_id: "storage",
          relative_path: "Client Docs",
          role: "generated",
          workspace_relative_path: "storage/generated/Client Docs",
        },
      ],
    }),
  );
  return dataTransfer;
}

describe("Storage drag reference parsing", () => {
  it("converts Storage selection payloads into chat mention items", () => {
    const dataTransfer = storageSelectionTransfer();

    expect(hasStorageReferenceDragData(dataTransfer)).toBe(true);
    expect(storageReferenceMentionItemsFromDataTransfer(dataTransfer)).toEqual([
      {
        id: "entity:storage:file:file_123",
        label: "report.md",
        description: "storage · file · markdown file in generated",
        kind: "entity",
        reference: {
          type: "entity",
          app_id: "storage",
          entity_type: "file",
          entity_id: "file_123",
          label: "report.md",
          summary: "markdown file in generated",
          deep_link: "/app/storage/files/file_123",
        },
      },
      {
        id: "entity:storage:folder:generated:Client%20Docs/",
        label: "Client Docs",
        description: "storage · folder · Storage folder in generated",
        kind: "entity",
        reference: {
          type: "entity",
          app_id: "storage",
          entity_type: "folder",
          entity_id: "generated:Client%20Docs/",
          label: "Client Docs",
          summary: "Storage folder in generated",
          deep_link: "/app/storage/folders/generated/Client%20Docs",
        },
      },
    ]);
  });

  it("rejects malformed Storage drag payloads", () => {
    const malformed = new FakeDataTransfer();
    malformed.setData(
      "application/x-maverick-storage-file",
      JSON.stringify({
        file_id: "file_123",
        name: "report.md",
        owner_app_id: "storage",
        relative_path: "../report.md",
        role: "generated",
        workspace_relative_path: "storage/generated/../report.md",
      }),
    );

    expect(hasStorageReferenceDragData(malformed)).toBe(true);
    expect(storageReferenceMentionItemsFromDataTransfer(malformed)).toEqual([]);
  });
});
