import { describe, expect, it } from "vitest";
import {
  appReferenceMentionItemsFromDataTransfer,
  hasAppReferenceDragData,
  hasStorageReferenceDragData,
  storageReferenceMentionItemsFromDataTransfer,
} from "./storageDragReferences";

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

  it("converts Checklist drag payloads into chat mention items", () => {
    const dataTransfer = new FakeDataTransfer();
    dataTransfer.setData(
      "application/x-maverick-checklist",
      JSON.stringify({
        checked_count: 2,
        checklist_id: "check_123",
        deep_link: "/app/checklist/checklists/check_123",
        mode: "agent_plan",
        owner_app_id: "checklist",
        status: "in-progress",
        summary: "Implement drag-to-chat checklist citations.",
        task_count: 4,
        title: "Checklist drag-to-chat citations",
      }),
    );

    expect(hasAppReferenceDragData(dataTransfer)).toBe(true);
    expect(hasStorageReferenceDragData(dataTransfer)).toBe(false);
    expect(appReferenceMentionItemsFromDataTransfer(dataTransfer)).toEqual([
      {
        id: "entity:checklist:checklist:check_123",
        label: "Checklist drag-to-chat citations",
        description: "checklist · checklist · Implement drag-to-chat checklist citations.",
        kind: "entity",
        reference: {
          type: "entity",
          app_id: "checklist",
          entity_type: "checklist",
          entity_id: "check_123",
          label: "Checklist drag-to-chat citations",
          summary: "Implement drag-to-chat checklist citations.",
          deep_link: "/app/checklist/checklists/check_123",
        },
      },
    ]);
  });

  it("converts Mail thread drag payloads into chat mention items", () => {
    const dataTransfer = new FakeDataTransfer();
    dataTransfer.setData(
      "application/x-maverick-mail-thread",
      JSON.stringify({
        connection_id: "mail_connection_gmail_person_example_com",
        deep_link: "/app/mail?thread=email_thread_gmail_person_example_com_thread_1",
        last_message_at: "2026-06-19T10:15:00+00:00",
        owner_app_id: "mail",
        sender: "Marco Giunti <marco@example.com>",
        snippet: "This message was automatically generated by Gmail.",
        subject: "unsubscribe",
        thread_id: "email_thread_gmail_person_example_com_thread_1",
        unread: false,
      }),
    );

    expect(hasAppReferenceDragData(dataTransfer)).toBe(true);
    expect(hasStorageReferenceDragData(dataTransfer)).toBe(false);
    expect(appReferenceMentionItemsFromDataTransfer(dataTransfer)).toEqual([
      {
        id: "entity:mail:email_thread:email_thread_gmail_person_example_com_thread_1",
        label: "unsubscribe",
        description: "mail · email_thread · This message was automatically generated by Gmail.",
        kind: "entity",
        reference: {
          type: "entity",
          app_id: "mail",
          entity_type: "email_thread",
          entity_id: "email_thread_gmail_person_example_com_thread_1",
          label: "unsubscribe",
          summary: "This message was automatically generated by Gmail.",
          deep_link: "/app/mail?thread=email_thread_gmail_person_example_com_thread_1",
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

    const malformedChecklist = new FakeDataTransfer();
    malformedChecklist.setData(
      "application/x-maverick-checklist",
      JSON.stringify({
        checked_count: 2,
        checklist_id: "check_123",
        deep_link: "/app/checklist/checklists/other",
        owner_app_id: "checklist",
        task_count: 4,
        title: "Checklist",
      }),
    );

    expect(hasAppReferenceDragData(malformedChecklist)).toBe(true);
    expect(appReferenceMentionItemsFromDataTransfer(malformedChecklist)).toEqual([]);

    const malformedMailThread = new FakeDataTransfer();
    malformedMailThread.setData(
      "application/x-maverick-mail-thread",
      JSON.stringify({
        deep_link: "/app/mail?thread=other",
        owner_app_id: "mail",
        subject: "Spoofed thread",
        thread_id: "email_thread_gmail_person_example_com_thread_1",
      }),
    );

    expect(hasAppReferenceDragData(malformedMailThread)).toBe(true);
    expect(appReferenceMentionItemsFromDataTransfer(malformedMailThread)).toEqual([]);
  });
});
