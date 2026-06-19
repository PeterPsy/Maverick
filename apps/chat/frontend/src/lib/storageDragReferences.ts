import type { AppReference } from "../api/client";
import { referenceKey } from "./mentions";
import type { MentionItem } from "./mentions";

const STORAGE_FILE_DRAG_DATA_TYPE = "application/x-maverick-storage-file";
const STORAGE_FOLDER_DRAG_DATA_TYPE = "application/x-maverick-storage-folder";
const STORAGE_SELECTION_DRAG_DATA_TYPE = "application/x-maverick-storage-selection";
const STORAGE_DRIVE_FILE_DRAG_DATA_TYPE = "application/x-maverick-storage-drive-file";
const STORAGE_DRIVE_FOLDER_DRAG_DATA_TYPE = "application/x-maverick-storage-drive-folder";
const CHECKLIST_DRAG_DATA_TYPE = "application/x-maverick-checklist";
const MAIL_THREAD_DRAG_DATA_TYPE = "application/x-maverick-mail-thread";

type StorageRole = "uploaded" | "generated";
type StoragePreviewKind =
  | "audio"
  | "document"
  | "file"
  | "image"
  | "markdown"
  | "pdf"
  | "presentation"
  | "spreadsheet"
  | "text"
  | "video";

type StorageFileDragPayload = {
  file_id: string;
  name: string;
  owner_app_id: string;
  preview_kind?: StoragePreviewKind;
  relative_path: string;
  role: StorageRole;
  workspace_relative_path: string;
};

type StorageFolderDragPayload = {
  folder_id: string;
  name: string;
  owner_app_id: string;
  relative_path: string;
  role: StorageRole;
  workspace_relative_path: string;
};

type StorageSelectionDragPayload = {
  files: StorageFileDragPayload[];
  folders: StorageFolderDragPayload[];
  owner_app_id: string;
};

type StorageDriveFileDragPayload = {
  connection_id: string;
  display_path: string;
  drive_file_id: string;
  file_id: string;
  name: string;
  owner_app_id: string;
  preview_kind?: StoragePreviewKind;
  provider: "google_drive";
  web_url?: string;
};

type StorageDriveBreadcrumbPayload = {
  connection_id: string;
  display_path: string;
  drive_file_id: string;
  label?: string;
};

type StorageDriveFolderDragPayload = {
  connection_id: string;
  display_path: string;
  drive_breadcrumbs?: StorageDriveBreadcrumbPayload[];
  drive_file_id: string;
  folder_id: string;
  name: string;
  owner_app_id: string;
  provider: "google_drive";
};

type ChecklistDragPayload = {
  checked_count: number;
  checklist_id: string;
  deep_link: string;
  mode: string;
  owner_app_id: string;
  status: string;
  summary: string;
  task_count: number;
  title: string;
};

type MailThreadDragPayload = {
  connection_id: string;
  deep_link: string;
  last_message_at: string;
  owner_app_id: string;
  sender: string;
  snippet: string;
  subject: string;
  thread_id: string;
  unread: boolean;
};

type StorageReferenceDataTransfer = Pick<DataTransfer, "getData" | "types">;
type StorageReferenceTypeDataTransfer = Pick<DataTransfer, "types">;

export function hasAppReferenceDragData(dataTransfer: StorageReferenceTypeDataTransfer): boolean {
  return (
    hasStorageReferenceDragData(dataTransfer) ||
    hasChecklistReferenceDragData(dataTransfer) ||
    hasMailReferenceDragData(dataTransfer)
  );
}

export function hasStorageReferenceDragData(dataTransfer: StorageReferenceTypeDataTransfer): boolean {
  const types = dataTransferTypes(dataTransfer);
  return (
    types.includes(STORAGE_FILE_DRAG_DATA_TYPE) ||
    types.includes(STORAGE_FOLDER_DRAG_DATA_TYPE) ||
    types.includes(STORAGE_SELECTION_DRAG_DATA_TYPE) ||
    types.includes(STORAGE_DRIVE_FILE_DRAG_DATA_TYPE) ||
    types.includes(STORAGE_DRIVE_FOLDER_DRAG_DATA_TYPE)
  );
}

export function appReferenceMentionItemsFromDataTransfer(dataTransfer: StorageReferenceDataTransfer): MentionItem[] {
  const references = [
    ...storageReferencesFromDataTransfer(dataTransfer),
    ...checklistReferencesFromDataTransfer(dataTransfer),
    ...mailReferencesFromDataTransfer(dataTransfer),
  ];
  return uniqueMentionItems(references);
}

export function storageReferenceMentionItemsFromDataTransfer(dataTransfer: StorageReferenceDataTransfer): MentionItem[] {
  const references = storageReferencesFromDataTransfer(dataTransfer);
  return uniqueMentionItems(references);
}

function uniqueMentionItems(references: AppReference[]): MentionItem[] {
  const byKey = new Map<string, MentionItem>();
  for (const reference of references) {
    byKey.set(referenceKey(reference), appReferenceMentionItem(reference));
  }
  return [...byKey.values()];
}

function storageReferencesFromDataTransfer(dataTransfer: StorageReferenceDataTransfer): AppReference[] {
  const selection = readStorageSelectionDragData(dataTransfer);
  const references: AppReference[] = [];
  if (selection) {
    references.push(
      ...selection.files.map(storageFileReference),
      ...selection.folders.map(storageFolderReference),
    );
  }
  const file = readStorageFileDragData(dataTransfer);
  if (file) {
    references.push(storageFileReference(file));
  }
  const folder = readStorageFolderDragData(dataTransfer);
  if (folder) {
    references.push(storageFolderReference(folder));
  }
  const driveFile = readStorageDriveFileDragData(dataTransfer);
  if (driveFile) {
    references.push(storageDriveFileReference(driveFile));
  }
  const driveFolder = readStorageDriveFolderDragData(dataTransfer);
  if (driveFolder) {
    references.push(storageDriveFolderReference(driveFolder));
  }
  return references;
}

function checklistReferencesFromDataTransfer(dataTransfer: StorageReferenceDataTransfer): AppReference[] {
  const checklist = readChecklistDragData(dataTransfer);
  return checklist ? [checklistReference(checklist)] : [];
}

function mailReferencesFromDataTransfer(dataTransfer: StorageReferenceDataTransfer): AppReference[] {
  const thread = readMailThreadDragData(dataTransfer);
  return thread ? [mailThreadReference(thread)] : [];
}

function readStorageFileDragData(dataTransfer: Pick<DataTransfer, "getData">): StorageFileDragPayload | null {
  return readStoragePayload(dataTransfer, STORAGE_FILE_DRAG_DATA_TYPE, normalizeStorageFileDragPayload);
}

function readStorageFolderDragData(dataTransfer: Pick<DataTransfer, "getData">): StorageFolderDragPayload | null {
  return readStoragePayload(dataTransfer, STORAGE_FOLDER_DRAG_DATA_TYPE, normalizeStorageFolderDragPayload);
}

function readStorageSelectionDragData(dataTransfer: Pick<DataTransfer, "getData">): StorageSelectionDragPayload | null {
  return readStoragePayload(dataTransfer, STORAGE_SELECTION_DRAG_DATA_TYPE, normalizeStorageSelectionDragPayload);
}

function readStorageDriveFileDragData(dataTransfer: Pick<DataTransfer, "getData">): StorageDriveFileDragPayload | null {
  return readStoragePayload(dataTransfer, STORAGE_DRIVE_FILE_DRAG_DATA_TYPE, normalizeStorageDriveFileDragPayload);
}

function readStorageDriveFolderDragData(dataTransfer: Pick<DataTransfer, "getData">): StorageDriveFolderDragPayload | null {
  return readStoragePayload(dataTransfer, STORAGE_DRIVE_FOLDER_DRAG_DATA_TYPE, normalizeStorageDriveFolderDragPayload);
}

function readChecklistDragData(dataTransfer: Pick<DataTransfer, "getData">): ChecklistDragPayload | null {
  return readStoragePayload(dataTransfer, CHECKLIST_DRAG_DATA_TYPE, normalizeChecklistDragPayload);
}

function readMailThreadDragData(dataTransfer: Pick<DataTransfer, "getData">): MailThreadDragPayload | null {
  return readStoragePayload(dataTransfer, MAIL_THREAD_DRAG_DATA_TYPE, normalizeMailThreadDragPayload);
}

function readStoragePayload<T>(
  dataTransfer: Pick<DataTransfer, "getData">,
  type: string,
  normalize: (payload: unknown) => T | null,
): T | null {
  const rawPayload = dataTransfer.getData(type);
  if (!rawPayload) {
    return null;
  }
  try {
    return normalize(JSON.parse(rawPayload));
  } catch {
    return null;
  }
}

function storageFileReference(payload: StorageFileDragPayload): AppReference {
  const previewKind = payload.preview_kind || previewKindFromFileName(payload.name);
  return {
    type: "entity",
    app_id: payload.owner_app_id,
    entity_type: "file",
    entity_id: payload.file_id,
    label: payload.name,
    summary: previewKind ? `${previewKind} file in ${payload.role}` : `Storage file in ${payload.role}`,
    deep_link: `/app/${encodeURIComponent(payload.owner_app_id)}/files/${encodeURIComponent(payload.file_id)}`,
  };
}

function storageFolderReference(payload: StorageFolderDragPayload): AppReference {
  const entityId = storageFolderEntityId(payload);
  const relativePath = encodedRelativePath(payload.relative_path);
  const appPath = relativePath ? `folders/${encodeURIComponent(payload.role)}/${relativePath}` : `folders/${encodeURIComponent(payload.role)}`;
  return {
    type: "entity",
    app_id: payload.owner_app_id,
    entity_type: "folder",
    entity_id: entityId,
    label: payload.name,
    summary: `Storage folder in ${payload.role}`,
    deep_link: `/app/${encodeURIComponent(payload.owner_app_id)}/${appPath}`,
  };
}

function storageDriveFileReference(payload: StorageDriveFileDragPayload): AppReference {
  const previewKind = payload.preview_kind || previewKindFromFileName(payload.name);
  return {
    type: "entity",
    app_id: payload.owner_app_id,
    entity_type: "file",
    entity_id: payload.file_id,
    label: payload.name,
    summary: previewKind ? `${previewKind} file in Google Drive` : "Google Drive file",
    deep_link: `/app/${encodeURIComponent(payload.owner_app_id)}/files/${encodeURIComponent(payload.file_id)}`,
  };
}

function storageDriveFolderReference(payload: StorageDriveFolderDragPayload): AppReference {
  const params = new URLSearchParams({
    provider: "google_drive",
    connection_id: payload.connection_id,
    drive_file_id: payload.drive_file_id,
    display_path: payload.display_path,
  });
  if (payload.drive_breadcrumbs?.length) {
    params.set("drive_breadcrumbs", JSON.stringify(payload.drive_breadcrumbs));
  }
  return {
    type: "entity",
    app_id: payload.owner_app_id,
    entity_type: "folder",
    entity_id: storageDriveFolderEntityId(payload),
    label: payload.name,
    summary: "Google Drive folder",
    deep_link: `/app/${encodeURIComponent(payload.owner_app_id)}?${params.toString()}`,
  };
}

function checklistReference(payload: ChecklistDragPayload): AppReference {
  return {
    type: "entity",
    app_id: payload.owner_app_id,
    entity_type: "checklist",
    entity_id: payload.checklist_id,
    label: payload.title,
    summary: payload.summary || `${payload.checked_count}/${payload.task_count} checked`,
    deep_link: payload.deep_link,
  };
}

function mailThreadReference(payload: MailThreadDragPayload): AppReference {
  return {
    type: "entity",
    app_id: payload.owner_app_id,
    entity_type: "email_thread",
    entity_id: payload.thread_id,
    label: payload.subject,
    summary: payload.snippet || (payload.sender ? `From ${payload.sender}` : "Mail thread"),
    deep_link: payload.deep_link,
  };
}

function appReferenceMentionItem(reference: AppReference): MentionItem {
  if (reference.type !== "entity") {
    return {
      id: reference.app_id,
      label: reference.label || reference.app_id,
      description: "",
      kind: "app",
      reference,
    };
  }
  return {
    id: referenceKey(reference),
    label: reference.label || reference.entity_id,
    description: [reference.app_id, reference.entity_type, reference.summary].filter(Boolean).join(" · "),
    kind: "entity",
    reference,
  };
}

function hasChecklistReferenceDragData(dataTransfer: StorageReferenceTypeDataTransfer): boolean {
  return dataTransferTypes(dataTransfer).includes(CHECKLIST_DRAG_DATA_TYPE);
}

function hasMailReferenceDragData(dataTransfer: StorageReferenceTypeDataTransfer): boolean {
  return dataTransferTypes(dataTransfer).includes(MAIL_THREAD_DRAG_DATA_TYPE);
}

function storageFolderEntityId(payload: StorageFolderDragPayload): string {
  const relativePath = encodedRelativePath(payload.relative_path);
  return relativePath ? `${payload.role}:${relativePath}/` : `${payload.role}:/`;
}

function storageDriveFolderEntityId(payload: StorageDriveFolderDragPayload): string {
  return `drive:${encodeURIComponent(payload.connection_id)}:${encodeURIComponent(payload.drive_file_id)}`;
}

function encodedRelativePath(value: string): string {
  return normalizeRelativePath(value)
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function normalizeStorageFileDragPayload(payload: unknown): StorageFileDragPayload | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const role = normalizeRole(record.role);
  const ownerAppId = normalizeRequiredText(record.owner_app_id);
  const fileId = normalizeReferenceId(record.file_id);
  const name = normalizeRequiredText(record.name);
  const previewKind = normalizePreviewKind(record.preview_kind);
  const relativePath = normalizeRelativePath(record.relative_path);
  const workspaceRelativePath = normalizeRelativePath(record.workspace_relative_path);

  if (!role || !ownerAppId || !fileId || !name || !relativePath || !workspaceRelativePath) {
    return null;
  }
  if (!workspaceRelativePath.startsWith(`storage/${role}/`)) {
    return null;
  }

  return {
    file_id: fileId,
    name,
    owner_app_id: ownerAppId,
    ...(previewKind ? { preview_kind: previewKind } : {}),
    relative_path: relativePath,
    role,
    workspace_relative_path: workspaceRelativePath,
  };
}

function normalizeStorageFolderDragPayload(payload: unknown): StorageFolderDragPayload | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const role = normalizeRole(record.role);
  const ownerAppId = normalizeRequiredText(record.owner_app_id);
  const folderId = normalizeRequiredText(record.folder_id);
  const name = normalizeRequiredText(record.name);
  const relativePath = normalizeRelativePath(record.relative_path);
  const workspaceRelativePath = normalizeRelativePath(record.workspace_relative_path);

  if (!role || !ownerAppId || !folderId || !name || !relativePath || !workspaceRelativePath) {
    return null;
  }
  if (workspaceRelativePath !== `storage/${role}/${relativePath}`) {
    return null;
  }

  return {
    folder_id: folderId,
    name,
    owner_app_id: ownerAppId,
    relative_path: relativePath,
    role,
    workspace_relative_path: workspaceRelativePath,
  };
}

function normalizeStorageSelectionDragPayload(payload: unknown): StorageSelectionDragPayload | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const ownerAppId = normalizeRequiredText(record.owner_app_id);
  if (!ownerAppId) {
    return null;
  }
  const files = normalizePayloadList(record.files, normalizeStorageFileDragPayload);
  const folders = normalizePayloadList(record.folders, normalizeStorageFolderDragPayload);
  if (!files || !folders || (!files.length && !folders.length)) {
    return null;
  }
  if ([...files, ...folders].some((item) => item.owner_app_id !== ownerAppId)) {
    return null;
  }
  return {
    files,
    folders,
    owner_app_id: ownerAppId,
  };
}

function normalizeStorageDriveFileDragPayload(payload: unknown): StorageDriveFileDragPayload | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const provider = record.provider === "google_drive" ? "google_drive" : null;
  const ownerAppId = normalizeRequiredText(record.owner_app_id);
  const fileId = normalizeReferenceId(record.file_id);
  const name = normalizeRequiredText(record.name);
  const connectionId = normalizeRequiredText(record.connection_id);
  const driveFileId = normalizeRequiredText(record.drive_file_id);
  const displayPath = normalizeDriveDisplayPath(record.display_path);
  const previewKind = normalizePreviewKind(record.preview_kind);
  const webUrl = normalizeOptionalHttpsUrl(record.web_url);

  if (!provider || !ownerAppId || !fileId || !name || !connectionId || !driveFileId || !displayPath) {
    return null;
  }
  return {
    connection_id: connectionId,
    display_path: displayPath,
    drive_file_id: driveFileId,
    file_id: fileId,
    name,
    owner_app_id: ownerAppId,
    ...(previewKind ? { preview_kind: previewKind } : {}),
    provider,
    ...(webUrl ? { web_url: webUrl } : {}),
  };
}

function normalizeStorageDriveFolderDragPayload(payload: unknown): StorageDriveFolderDragPayload | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const provider = record.provider === "google_drive" ? "google_drive" : null;
  const ownerAppId = normalizeRequiredText(record.owner_app_id);
  const folderId = normalizeRequiredText(record.folder_id);
  const name = normalizeRequiredText(record.name);
  const connectionId = normalizeRequiredText(record.connection_id);
  const driveFileId = normalizeRequiredText(record.drive_file_id);
  const displayPath = normalizeDriveDisplayPath(record.display_path);
  const driveBreadcrumbs = normalizeStorageDriveBreadcrumbPayloads(record.drive_breadcrumbs, connectionId);

  if (!provider || !ownerAppId || !folderId || !name || !connectionId || !driveFileId || !displayPath || !driveBreadcrumbs) {
    return null;
  }
  return {
    connection_id: connectionId,
    display_path: displayPath,
    ...(driveBreadcrumbs.length ? { drive_breadcrumbs: driveBreadcrumbs } : {}),
    drive_file_id: driveFileId,
    folder_id: folderId,
    name,
    owner_app_id: ownerAppId,
    provider,
  };
}

function normalizeChecklistDragPayload(payload: unknown): ChecklistDragPayload | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const ownerAppId = normalizeRequiredText(record.owner_app_id);
  const checklistId = normalizeReferenceId(record.checklist_id);
  const title = normalizeRequiredText(record.title);
  const summary = normalizeRequiredText(record.summary);
  const mode = normalizeRequiredText(record.mode);
  const status = normalizeRequiredText(record.status);
  const taskCount = normalizeNonNegativeInteger(record.task_count);
  const checkedCount = normalizeNonNegativeInteger(record.checked_count);
  const deepLink = normalizeChecklistDeepLink(record.deep_link, ownerAppId, checklistId);

  if (!ownerAppId || !checklistId || !title || !deepLink || taskCount === null || checkedCount === null) {
    return null;
  }
  return {
    checked_count: Math.min(checkedCount, taskCount),
    checklist_id: checklistId,
    deep_link: deepLink,
    mode,
    owner_app_id: ownerAppId,
    status,
    summary,
    task_count: taskCount,
    title,
  };
}

function normalizeMailThreadDragPayload(payload: unknown): MailThreadDragPayload | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const ownerAppId = normalizeRequiredText(record.owner_app_id);
  const threadId = normalizeReferenceId(record.thread_id);
  const deepLink = normalizeMailThreadDeepLink(record.deep_link, ownerAppId, threadId);
  if (!ownerAppId || !threadId || !deepLink) {
    return null;
  }
  return {
    connection_id: normalizeReferenceId(record.connection_id),
    deep_link: deepLink,
    last_message_at: normalizeRequiredText(record.last_message_at),
    owner_app_id: ownerAppId,
    sender: normalizeRequiredText(record.sender),
    snippet: normalizeRequiredText(record.snippet),
    subject: normalizeRequiredText(record.subject) || "Email thread",
    thread_id: threadId,
    unread: typeof record.unread === "boolean" ? record.unread : false,
  };
}

function normalizeStorageDriveBreadcrumbPayloads(value: unknown, fallbackConnectionId: string): StorageDriveBreadcrumbPayload[] | null {
  if (value === undefined) {
    return [];
  }
  if (!Array.isArray(value)) {
    return null;
  }
  const payloads = value.map((item) => normalizeStorageDriveBreadcrumbPayload(item, fallbackConnectionId));
  if (payloads.some((item) => !item)) {
    return null;
  }
  const byPath = new Map<string, StorageDriveBreadcrumbPayload>();
  (payloads as StorageDriveBreadcrumbPayload[]).forEach((target) => byPath.set(target.display_path, target));
  return [...byPath.values()];
}

function normalizeStorageDriveBreadcrumbPayload(value: unknown, fallbackConnectionId: string): StorageDriveBreadcrumbPayload | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const connectionId = normalizeRequiredText(record.connection_id) || normalizeRequiredText(record.connectionId) || fallbackConnectionId;
  const displayPath = normalizeDriveDisplayPath(record.display_path || record.displayPath || record.path);
  const driveFileId = normalizeRequiredText(record.drive_file_id) || normalizeRequiredText(record.driveFileId);
  const label = normalizeRequiredText(record.label);
  if (!connectionId || connectionId !== fallbackConnectionId || !displayPath || !driveFileId) {
    return null;
  }
  return {
    connection_id: connectionId,
    display_path: displayPath,
    drive_file_id: driveFileId,
    ...(label ? { label } : {}),
  };
}

function normalizePayloadList<T>(value: unknown, normalize: (item: unknown) => T | null): T[] | null {
  if (value === undefined) {
    return [];
  }
  if (!Array.isArray(value)) {
    return null;
  }
  const normalized = value.map((item) => normalize(item));
  if (normalized.some((item) => !item)) {
    return null;
  }
  return normalized as T[];
}

function normalizeRole(value: unknown): StorageRole | null {
  return value === "uploaded" || value === "generated" ? value : null;
}

function normalizePreviewKind(value: unknown): StoragePreviewKind | null {
  return value === "image" ||
    value === "video" ||
    value === "audio" ||
    value === "markdown" ||
    value === "text" ||
    value === "pdf" ||
    value === "document" ||
    value === "presentation" ||
    value === "spreadsheet" ||
    value === "file"
    ? value
    : null;
}

function previewKindFromFileName(name: string): StoragePreviewKind | null {
  const extension = name.split(".").pop()?.toLowerCase() || "";
  if (["apng", "avif", "bmp", "gif", "heic", "jpeg", "jpg", "png", "svg", "webp"].includes(extension)) {
    return "image";
  }
  if (["avi", "m4v", "mov", "mp4", "mpeg", "mpg", "webm"].includes(extension)) {
    return "video";
  }
  if (["aac", "flac", "m4a", "mp3", "ogg", "opus", "wav", "weba"].includes(extension)) {
    return "audio";
  }
  if (["markdown", "md", "mdx"].includes(extension)) {
    return "markdown";
  }
  if (["csv", "json", "log", "text", "txt", "xml", "yaml", "yml"].includes(extension)) {
    return "text";
  }
  if (extension === "pdf") {
    return "pdf";
  }
  if (["doc", "docx", "odt", "rtf"].includes(extension)) {
    return "document";
  }
  if (["odp", "ppt", "pptx"].includes(extension)) {
    return "presentation";
  }
  if (["ods", "xls", "xlsx"].includes(extension)) {
    return "spreadsheet";
  }
  return null;
}

function normalizeRequiredText(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function normalizeReferenceId(value: unknown): string {
  const id = normalizeRequiredText(value);
  return id && !/\s/.test(id) ? id : "";
}

function normalizeNonNegativeInteger(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    return null;
  }
  return value;
}

function normalizeChecklistDeepLink(value: unknown, ownerAppId: string, checklistId: string): string {
  if (typeof value !== "string" || !ownerAppId || !checklistId) {
    return "";
  }
  const expected = `/app/${encodeURIComponent(ownerAppId)}/checklists/${encodeURIComponent(checklistId)}`;
  return value.trim() === expected ? expected : "";
}

function normalizeMailThreadDeepLink(value: unknown, ownerAppId: string, threadId: string): string {
  if (typeof value !== "string" || !ownerAppId || !threadId) {
    return "";
  }
  const params = new URLSearchParams({ thread: threadId });
  const expected = `/app/${encodeURIComponent(ownerAppId)}?${params.toString()}`;
  return value.trim() === expected ? expected : "";
}

function normalizeRelativePath(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  const parts = value.split("/").filter(Boolean);
  if (!parts.length || parts.some((part) => part === "." || part === "..")) {
    return "";
  }
  return parts.join("/");
}

function normalizeDriveDisplayPath(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  const parts = value.split("/").filter(Boolean);
  if (!parts.length || parts.some((part) => part === "." || part === "..")) {
    return "";
  }
  return `/${parts.join("/")}`;
}

function normalizeOptionalHttpsUrl(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  try {
    const url = new URL(trimmed);
    return url.protocol === "https:" ? url.toString() : "";
  } catch {
    return "";
  }
}

function dataTransferTypes(dataTransfer: StorageReferenceTypeDataTransfer): string[] {
  return Array.from(dataTransfer.types || []).map((type) => String(type).toLowerCase());
}
