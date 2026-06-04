export type FileRole = 'uploaded' | 'generated';
export type StorageProvider = 'local' | 'google_drive';
export type StorageItemRole = FileRole | '';

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
  provider?: StorageProvider;
  connection_id?: string;
  drive_file_id?: string;
  display_path?: string;
  remote_locator?: Record<string, unknown>;
  capabilities?: StorageProviderCapabilities;
  role: StorageItemRole;
  name: string;
  relative_path: string;
  workspace_relative_path: string;
  extension: string;
  size_bytes: number;
  created_at?: string;
  modified_at: string;
  content_type: string;
  preview_kind: PreviewKind;
  sha256: string;
};

export type StorageFolder = {
  id: string;
  provider?: StorageProvider;
  connection_id?: string;
  drive_file_id?: string;
  display_path?: string;
  remote_locator?: Record<string, unknown>;
  capabilities?: StorageProviderCapabilities;
  role: StorageItemRole;
  name: string;
  relative_path: string;
  workspace_relative_path: string;
  modified_at: string;
};

export type StorageProviderCapabilities = {
  can_read: boolean;
  can_write: boolean;
  can_move: boolean;
  can_rename: boolean;
  can_delete: boolean;
  can_preview: boolean;
  can_index: boolean;
};

export type DriveConnection = {
  id: string;
  resource_type: 'drive_connection';
  provider: 'google_drive';
  account_email: string;
  display_name: string;
  status: 'pending' | 'connected' | 'disconnected' | 'error';
  access_mode: string;
  scopes: string[];
  created_at: string;
  updated_at: string;
  connected_at: string;
  disconnected_at: string;
  credential?: {
    secret_ref?: string;
    grant_id?: string;
    status?: string;
    oauth_metadata?: Record<string, unknown>;
  };
  external_refs?: Record<string, unknown>;
  sync_state?: {
    start_page_token: string;
    last_processed_page_token: string;
    last_sync_at: string;
    status: 'not_started' | 'healthy' | 'syncing' | 'error';
    error: string;
  };
};

export type DriveConnectionsPayload = {
  connections: DriveConnection[];
  provider: 'google_drive';
};

export type DriveStartOAuthPayload = {
  access_mode: string;
  authorization_url?: string;
  connection_id?: string;
  missing_secrets?: string[];
  provider: 'google_drive';
  state?: string;
  status: 'authorization_required' | 'not_configured';
};

export type DriveCompleteOAuthPayload = {
  access_mode: string;
  connection?: DriveConnection;
  connection_id?: string;
  provider: 'google_drive';
  status: 'connected' | 'needs_secret_grant';
};

export type DriveDisconnectPayload = {
  connection: DriveConnection;
  connection_id: string;
  status: 'disconnected';
};

export type DriveListPayload = {
  provider: 'google_drive';
  connection_id: string;
  files?: StorageFile[];
  folders?: StorageFolder[];
  pagination?: {
    limit: number;
    total: number;
    has_more: boolean;
    next_page_token?: string;
  };
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
  available_kinds: PreviewKind[];
  pagination?: {
    offset: number;
    limit: number | null;
    total: number;
    has_more: boolean;
    next_page_token?: string;
  };
  inventory?: {
    schema_version: string;
    updated_at: string;
  };
};

export type ReadFilePayload = {
  file: StorageFile;
  content_base64: string;
  content_type?: string;
  file_name?: string;
};

export type DrivePreviewPayload = {
  file: StorageFile;
  content_base64?: string;
  content_type?: string;
  file_name?: string;
  preview_text?: string;
  export_mime_type?: string;
  bytes_read?: number;
  cache_hit?: boolean;
  preview_truncated?: boolean;
  truncated?: boolean;
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

export type MoveFolderPayload = {
  folder: StorageFolder;
};

export type MoveItemPrevious = {
  role: FileRole;
  relative_path: string;
  workspace_relative_path: string;
};

export type MoveItemsPayload = {
  files: { previous: MoveItemPrevious; file: StorageFile }[];
  folders: { previous: MoveItemPrevious; folder: StorageFolder }[];
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
