export type BackendStatus = {
  app_id?: string;
  workspace_id?: string | null;
  status?: string;
  [key: string]: unknown;
};

export async function callBackend<T = BackendStatus>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/video-studio/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`Backend request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}
