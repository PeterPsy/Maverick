export async function callBackend<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/skills/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || 'Skills request failed');
  }
  return payload as T;
}
