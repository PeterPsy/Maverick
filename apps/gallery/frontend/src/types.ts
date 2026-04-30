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

export type GalleryFile = {
  id: string;
  role: FileRole;
  name: string;
  relative_path: string;
  workspace_relative_path: string;
  extension: string;
  size_bytes: number;
  modified_at: string;
  content_type: string;
  preview_kind: PreviewKind;
};

export type GalleryFolder = {
  id: string;
  role: FileRole;
  name: string;
  relative_path: string;
  workspace_relative_path: string;
  modified_at: string;
};

export type GalleryViewFilter = {
  mode: 'search' | 'custom';
  title: string;
  query: string;
  role: FileRole | 'all';
  kind: PreviewKind | 'all';
  file_ids: string[];
  workspace_relative_paths: string[];
  updated_at: string;
};

export type GalleryState = {
  schema_version: string;
  view_mode: string;
  view_filter: GalleryViewFilter;
};

export type CatalogPayload = {
  state: GalleryState;
  files: GalleryFile[];
  folders: GalleryFolder[];
};

export type ReadFilePayload = {
  file: GalleryFile;
  content_base64: string;
};

export type DeleteFilePayload = {
  deleted: boolean;
  file: GalleryFile;
};

export type UpdateMarkdownPayload = {
  file: GalleryFile;
};

export type CreateFolderPayload = {
  folder: GalleryFolder;
};

export type MoveFilePayload = {
  file: GalleryFile;
};

export type UploadFilePayload = {
  file: GalleryFile;
  bytes_written: number;
};

export type TablePreviewSheet = {
  name: string;
  rows: string[][];
  truncated_rows: boolean;
  truncated_columns: boolean;
};

export type PreviewTextPayload = {
  file: GalleryFile;
  preview_text: string;
  cache_hit?: boolean;
};

export type PreviewTablePayload = {
  file: GalleryFile;
  sheets: TablePreviewSheet[];
};

export type RenderPreviewPayload = {
  file: GalleryFile;
  content_base64: string;
  content_type: 'application/pdf' | 'image/png';
  preview_kind: 'pdf' | 'image';
  renderer: 'native' | 'libreoffice';
  cache_hit?: boolean;
};
