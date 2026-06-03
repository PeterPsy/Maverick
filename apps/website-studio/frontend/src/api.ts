export type BackendStatus = {
  app_id?: string;
  workspace_id?: string | null;
  status?: string;
  [key: string]: unknown;
};

export type Site = {
  id: string;
  display_name: string;
  slug: string;
  status: string;
  source_provider: string;
  active_revision_id?: string | null;
  published_revision_id?: string | null;
};

export type Page = {
  id: string;
  site_id: string;
  route: string;
  title: string;
  kind: string;
  status: string;
  source_files: string[];
};

export type WebsiteFile = {
  site_id: string;
  path: string;
  content: string;
  hash: string;
  revision_id?: string | null;
};

export type DiffFile = {
  path: string;
  status: string;
  patch: string;
};

export type StorageFile = {
  id?: string;
  file_id?: string;
  workspace_relative_path?: string;
  role?: string;
  relative_path?: string;
  name?: string;
  content_type?: string;
  sha256?: string;
};

export async function callBackend<T = BackendStatus>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/website-studio/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(String(payload.detail || payload.error || `Backend request failed with ${response.status}`));
  }
  return response.json() as Promise<T>;
}

export async function callStorage<T = { file?: StorageFile }>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/storage/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(String(payload.detail || payload.error || `Storage request failed with ${response.status}`));
  }
  return response.json() as Promise<T>;
}
