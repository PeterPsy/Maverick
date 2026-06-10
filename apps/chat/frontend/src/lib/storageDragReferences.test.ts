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

  it("converts Drive drag payloads into chat mention items", () => {
    const dataTransfer = new FakeDataTransfer();
    const driveBreadcrumbs = [
      {
        connection_id: "drive_conn_1",
        display_path: "/My Drive",
        drive_file_id: "root",
        label: "My Drive",
      },
      {
        connection_id: "drive_conn_1",
        display_path: "/My Drive/Reports",
        drive_file_id: "drive_folder_1",
        label: "Reports",
      },
    ];
    const driveFolderParams = new URLSearchParams({
      provider: "google_drive",
      connection_id: "drive_conn_1",
      drive_file_id: "drive_folder_1",
      display_path: "/My Drive/Reports",
    });
    driveFolderParams.set("drive_breadcrumbs", JSON.stringify(driveBreadcrumbs));
    dataTransfer.setData(
      "application/x-maverick-storage-drive-file",
      JSON.stringify({
        connection_id: "drive_conn_1",
        display_path: "/My Drive/Reports/summary.pdf",
        drive_file_id: "drive_file_1",
        file_id: "file_drive_1",
        name: "summary.pdf",
        owner_app_id: "storage",
        preview_kind: "pdf",
        provider: "google_drive",
      }),
    );
    dataTransfer.setData(
      "application/x-maverick-storage-drive-folder",
      JSON.stringify({
        connection_id: "drive_conn_1",
        display_path: "/My Drive/Reports",
        drive_breadcrumbs: driveBreadcrumbs,
        drive_file_id: "drive_folder_1",
        folder_id: "folder_drive_1",
        name: "Reports",
        owner_app_id: "storage",
        provider: "google_drive",
      }),
    );

    expect(hasStorageReferenceDragData(dataTransfer)).toBe(true);
    expect(storageReferenceMentionItemsFromDataTransfer(dataTransfer)).toEqual([
      {
        id: "entity:storage:file:file_drive_1",
        label: "summary.pdf",
        description: "storage · file · pdf file in Google Drive",
        kind: "entity",
        reference: {
          type: "entity",
          app_id: "storage",
          entity_type: "file",
          entity_id: "file_drive_1",
          label: "summary.pdf",
          summary: "pdf file in Google Drive",
          deep_link: "/app/storage/files/file_drive_1",
        },
      },
      {
        id: "entity:storage:folder:drive:drive_conn_1:drive_folder_1",
        label: "Reports",
        description: "storage · folder · Google Drive folder",
        kind: "entity",
        reference: {
          type: "entity",
          app_id: "storage",
          entity_type: "folder",
          entity_id: "drive:drive_conn_1:drive_folder_1",
          label: "Reports",
          summary: "Google Drive folder",
          deep_link: `/app/storage?${driveFolderParams.toString()}`,
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

    const malformedDrive = new FakeDataTransfer();
    malformedDrive.setData(
      "application/x-maverick-storage-drive-file",
      JSON.stringify({
        connection_id: "drive_conn_1",
        display_path: "/../secret",
        drive_file_id: "drive_file_1",
        file_id: "file_drive_1",
        name: "secret.pdf",
        owner_app_id: "storage",
        provider: "google_drive",
      }),
    );

    expect(hasStorageReferenceDragData(malformedDrive)).toBe(true);
    expect(storageReferenceMentionItemsFromDataTransfer(malformedDrive)).toEqual([]);
  });
});
