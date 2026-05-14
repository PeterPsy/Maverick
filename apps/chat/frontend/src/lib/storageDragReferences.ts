import type { AppReference } from "../api/client";
import { referenceKey } from "./mentions";
import type { MentionItem } from "./mentions";

const STORAGE_FILE_DRAG_DATA_TYPE = "application/x-maverick-storage-file";
const STORAGE_FOLDER_DRAG_DATA_TYPE = "application/x-maverick-storage-folder";
const STORAGE_SELECTION_DRAG_DATA_TYPE = "application/x-maverick-storage-selection";

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

type StorageReferenceDataTransfer = Pick<DataTransfer, "getData" | "types">;
type StorageReferenceTypeDataTransfer = Pick<DataTransfer, "types">;

export function hasStorageReferenceDragData(dataTransfer: StorageReferenceTypeDataTransfer): boolean {
  const types = dataTransferTypes(dataTransfer);
  return (
    types.includes(STORAGE_FILE_DRAG_DATA_TYPE) ||
    types.includes(STORAGE_FOLDER_DRAG_DATA_TYPE) ||
    types.includes(STORAGE_SELECTION_DRAG_DATA_TYPE)
  );
}

export function storageReferenceMentionItemsFromDataTransfer(dataTransfer: StorageReferenceDataTransfer): MentionItem[] {
  const references = storageReferencesFromDataTransfer(dataTransfer);
  const byKey = new Map<string, MentionItem>();
  for (const reference of references) {
    byKey.set(referenceKey(reference), storageReferenceMentionItem(reference));
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
  return references;
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

function storageReferenceMentionItem(reference: AppReference): MentionItem {
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

function storageFolderEntityId(payload: StorageFolderDragPayload): string {
  const relativePath = encodedRelativePath(payload.relative_path);
  return relativePath ? `${payload.role}:${relativePath}/` : `${payload.role}:/`;
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

function dataTransferTypes(dataTransfer: StorageReferenceTypeDataTransfer): string[] {
  return Array.from(dataTransfer.types || []).map((type) => String(type).toLowerCase());
}
