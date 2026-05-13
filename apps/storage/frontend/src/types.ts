export type FileRole = 'uploaded' | 'generated';

export type PreviewKind =
  | 'image'
  | 'video'
  | 'audio'
  | 'markdown'
  | 'text'
  | 'pdf'
  | 'document'
  | 'presentation'
  | 'spreadsheet'
  | 'file';

export type StorageFile = {
  id: string;
  file_id: string;
  path_id: string;
  role: FileRole;
  name: string;
  relative_path: string;
  workspace_relative_path: string;
  extension: string;
  size_bytes: number;
  modified_at: string;
  content_type: string;
  preview_kind: PreviewKind;
  sha256: string;
};

export type StorageFolder = {
  id: string;
  role: FileRole;
  name: string;
  relative_path: string;
  workspace_relative_path: string;
  modified_at: string;
};

export type StorageViewFilter = {
  mode: 'search' | 'custom';
  title: string;
  query: string;
  role: FileRole | 'all';
  kind: PreviewKind | 'all';
  file_ids: string[];
  workspace_relative_paths: string[];
  updated_at: string;
};

export type StorageState = {
  schema_version: string;
  view_mode: string;
  view_filter: StorageViewFilter;
};

export type CatalogPayload = {
  state: StorageState;
  files: StorageFile[];
  folders: StorageFolder[];
  pagination?: {
    offset: number;
    limit: number | null;
    total: number;
    has_more: boolean;
  };
  inventory?: {
    schema_version: string;
    updated_at: string;
  };
};

export type ReadFilePayload = {
  file: StorageFile;
  content_base64: string;
};

export type DeleteFilePayload = {
  deleted: boolean;
  file: StorageFile;
};

export type DeleteFolderPayload = {
  deleted: boolean;
  folder: StorageFolder;
};

export type DownloadFolderPayload = {
  content_base64: string;
  content_type: 'application/zip';
  file_name: string;
  folder: StorageFolder;
};

export type UpdateMarkdownPayload = {
  file: StorageFile;
};

export type CreateFolderPayload = {
  folder: StorageFolder;
};

export type MoveFilePayload = {
  file: StorageFile;
};

export type UploadFilePayload = {
  file: StorageFile;
  bytes_written: number;
};

export type TablePreviewSheet = {
  name: string;
  rows: string[][];
  truncated_rows: boolean;
  truncated_columns: boolean;
};

export type PreviewTextPayload = {
  file: StorageFile;
  preview_text: string;
  cache_hit?: boolean;
};

export type PreviewTablePayload = {
  file: StorageFile;
  sheets: TablePreviewSheet[];
};

export type RenderPreviewPayload = {
  file: StorageFile;
  content_base64: string;
  content_type: 'application/pdf' | 'image/png';
  preview_kind: 'pdf' | 'image';
  renderer: 'native' | 'libreoffice';
  cache_hit?: boolean;
};
