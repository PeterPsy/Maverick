export class ApiError extends Error {
  path: string;
  status: number;

  constructor(message: string, { path, status }: { path: string; status: number }) {
    super(message);
    this.name = "ApiError";
    this.path = path;
    this.status = status;
  }
}

export async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { Accept: "application/json", ...(init.headers || {}) },
  });
  if (!response.ok) {
    let detail = `Request failed ${response.status}: ${path}`;
    try {
      const payload = (await response.json()) as { detail?: string; error?: string };
      detail = payload.detail || payload.error || detail;
    } catch {
      // Keep the HTTP fallback detail.
    }
    throw new ApiError(detail, { path, status: response.status });
  }
  return (await response.json()) as T;
}

export function stringField(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function stringArrayField(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function booleanField(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function objectField(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}
