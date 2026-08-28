export class BackendRequestError extends Error {
  readonly code: string;
  readonly status: number;
  readonly phase: string;
  readonly autoRepairable: boolean;
  readonly retryable: boolean;

  constructor(payload: Record<string, unknown>, status: number) {
    const code = safeDiagnosticCode(payload.error, "backend_request_failed");
    super(typeof payload.detail === "string" && payload.detail.trim()
      ? payload.detail
      : "Design Studio request failed.");
    this.name = "BackendRequestError";
    this.code = code;
    this.status = status;
    this.phase = safeDiagnosticCode(payload.phase, "backend");
    this.autoRepairable = payload.auto_repairable === true;
    this.retryable = typeof payload.retryable === "boolean"
      ? payload.retryable
      : status >= 500;
  }
}

export async function callDesignStudioBackend<T>(
  action: string,
  argumentsPayload: Record<string, unknown> = {},
  appId = mountedAppId(),
  options: { signal?: AbortSignal } = {},
): Promise<T> {
  const response = await fetch(`/api/apps/${encodeURIComponent(appId)}/backend`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ action, arguments: argumentsPayload }),
    signal: options.signal,
  });
  const rawPayload = await response.json() as unknown;
  const payload = rawPayload && typeof rawPayload === "object" && !Array.isArray(rawPayload)
    ? rawPayload as Record<string, unknown> & T
    : {} as Record<string, unknown> & T;
  if (!response.ok || typeof payload.error === "string") {
    throw new BackendRequestError(payload, response.status);
  }
  return payload as T;
}

export function mountedAppId(pathname = window.location.pathname): string {
  const match = /^\/apps\/([^/?#]+)/.exec(pathname);
  return match?.[1] || "design-studio";
}

export function projectCreatedAt(project: Record<string, unknown>): number {
  const value = project.createdAt ?? project.created_at ?? 0;
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.abs(value) < 100_000_000_000 ? value * 1000 : value;
  }
  if (typeof value !== "string") {
    return 0;
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric) && value.trim()) {
    return Math.abs(numeric) < 100_000_000_000 ? numeric * 1000 : numeric;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function nextDefaultProjectName(projects: Array<Record<string, unknown>>): string {
  const base = "Progetto senza titolo";
  const existing = new Set(
    projects
      .map((project) => typeof project.name === "string" ? project.name.trim() : "")
      .filter(Boolean)
      .map((name) => name.normalize("NFKC").toLocaleLowerCase("it-IT")),
  );
  if (!existing.has(base.toLocaleLowerCase("it-IT"))) {
    return base;
  }
  for (let suffix = 2; suffix <= existing.size + 1; suffix += 1) {
    const candidate = `${base} ${suffix}`;
    if (!existing.has(candidate.toLocaleLowerCase("it-IT"))) {
      return candidate;
    }
  }
  throw new Error("Unable to allocate a default project name.");
}

export function projectIdFromWidgetMessage(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return "";
  }
  const message = value as Record<string, unknown>;
  if (message.type === "maverick.app.selection-changed") {
    return scalarProjectId((message.selection as Record<string, unknown> | undefined)?.od_project_id);
  }
  if (message.type !== "maverick.widget.context-changed") {
    return "";
  }
  const context = message.context as Record<string, unknown> | undefined;
  const content = context?.content as Record<string, unknown> | undefined;
  const payload = content?.payload as Record<string, unknown> | undefined;
  const params = payload?.active_app_params as Record<string, unknown> | undefined;
  return scalarProjectId(params?.od_project_id || params?.project_id);
}

export function mobileLayoutFromWidgetMessage(value: unknown): boolean | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const message = value as Record<string, unknown>;
  if (message.type !== "maverick.widget.context-changed") {
    return undefined;
  }
  const context = message.context as Record<string, unknown> | undefined;
  const content = context?.content as Record<string, unknown> | undefined;
  const payload = content?.payload as Record<string, unknown> | undefined;
  return typeof payload?.is_mobile_layout === "boolean" ? payload.is_mobile_layout : undefined;
}

function scalarProjectId(value: unknown): string {
  const text = typeof value === "string" ? value.trim() : "";
  return /^[A-Za-z0-9_][A-Za-z0-9._~-]{0,127}$/.test(text) ? text : "";
}

function safeDiagnosticCode(value: unknown, fallback: string): string {
  return typeof value === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(value)
    ? value
    : fallback;
}
