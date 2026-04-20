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

export type CatalogPayload = {
  files: GalleryFile[];
};

export type ReadFilePayload = {
  file: GalleryFile;
  content_base64: string;
};

export type DeleteFilePayload = {
  deleted: boolean;
  file: GalleryFile;
};

export type PreviewTextPayload = {
  file: GalleryFile;
  preview_text: string;
};
