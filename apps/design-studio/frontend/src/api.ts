import type { SidecarLaunch } from "./types";

const IDENTIFIER = /^[A-Za-z0-9_][A-Za-z0-9._~-]{0,127}$/;
const BOOTSTRAP_PATH = "/.well-known/maverick-sidecar-bootstrap";

export class SidecarLaunchError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, status: number) {
    super("OpenDesign could not be opened through its governed browser origin.");
    this.name = "SidecarLaunchError";
    this.code = code;
    this.status = status;
  }
}

export function currentDesignStudioAppId(pathname = window.location.pathname): string {
  return /^\/apps\/([^/?#]+)/.exec(pathname)?.[1] || "design-studio";
}

export function nativeOpenDesignPath(
  input: string | URLSearchParams | Record<string, unknown> = window.location.search,
): string {
  const params = typeof input === "string"
    ? Object.fromEntries(new URLSearchParams(input).entries())
    : input instanceof URLSearchParams
      ? Object.fromEntries(input.entries())
      : input;
  const appPage = nativePathFromAppPage(params.app_page);
  if (appPage !== undefined) return appPage;
  const projectId = scalar(params.od_project_id ?? params.project_id);
  const conversationId = scalar(params.od_conversation_id ?? params.conversation_id);
  if (projectId && conversationId) {
    return `/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(conversationId)}`;
  }
  return projectId ? `/projects/${encodeURIComponent(projectId)}` : "/";
}

function nativePathFromAppPage(value: unknown): string | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  if (typeof value !== "string") return "/";
  const segments = value.trim().split("/");
  if (
    segments.length === 2
    && segments[0] === "projects"
    && IDENTIFIER.test(segments[1])
  ) {
    return `/projects/${encodeURIComponent(segments[1])}`;
  }
  if (
    segments.length === 4
    && segments[0] === "projects"
    && IDENTIFIER.test(segments[1])
    && segments[2] === "conversations"
    && IDENTIFIER.test(segments[3])
  ) {
    return `/projects/${encodeURIComponent(segments[1])}/conversations/${encodeURIComponent(segments[3])}`;
  }
  return "/";
}

export async function requestOpenDesignLaunch(
  appId: string,
  path: string,
  platformOrigin = window.location.origin,
  signal?: AbortSignal,
): Promise<SidecarLaunch> {
  if (!isNativePath(path)) throw new SidecarLaunchError("sidecar_launch_path_invalid", 0);
  const response = await fetch("/api/app-sidecars/browser-launch", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify({ app_id: appId, sidecar_id: "opendesign", path }),
  });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new SidecarLaunchError("sidecar_launch_response_invalid", response.status);
  }
  if (!response.ok) {
    const code = isRecord(payload) && typeof payload.error === "string"
      ? safeErrorCode(payload.error)
      : "browser_ticket_failed";
    throw new SidecarLaunchError(code, response.status);
  }
  return validateSidecarLaunch(payload, platformOrigin);
}

export function validateSidecarLaunch(payload: unknown, platformOrigin: string): SidecarLaunch {
  if (!isRecord(payload)) throw new SidecarLaunchError("sidecar_launch_response_invalid", 502);
  const candidate = payload as Partial<SidecarLaunch>;
  if (
    typeof candidate.origin !== "string"
    || typeof candidate.bootstrap_url !== "string"
    || candidate.method !== "POST"
    || candidate.ticket_field !== "ticket"
    || typeof candidate.ticket !== "string"
    || !candidate.ticket
    || candidate.ticket.length > 512
    || /\s/.test(candidate.ticket)
    || !Number.isInteger(candidate.expires_in_seconds)
    || Number(candidate.expires_in_seconds) < 1
    || Number(candidate.expires_in_seconds) > 30
    || typeof candidate.sidecar_instance_id !== "string"
    || !/^[A-Za-z0-9_-]{8,128}$/.test(candidate.sidecar_instance_id)
  ) {
    throw new SidecarLaunchError("sidecar_launch_response_invalid", 502);
  }
  try {
    const isolated = new URL(candidate.origin);
    const bootstrap = new URL(candidate.bootstrap_url);
    const platform = new URL(platformOrigin);
    if (
      isolated.origin !== candidate.origin
      || isolated.origin === platform.origin
      || !["http:", "https:"].includes(isolated.protocol)
      || isolated.username
      || isolated.password
      || bootstrap.origin !== isolated.origin
      || bootstrap.pathname !== BOOTSTRAP_PATH
      || bootstrap.search
      || bootstrap.hash
    ) {
      throw new Error("invalid launch boundary");
    }
  } catch {
    throw new SidecarLaunchError("sidecar_launch_response_invalid", 502);
  }
  return candidate as SidecarLaunch;
}

function isNativePath(path: string): boolean {
  return path === "/" || /^\/projects\/[A-Za-z0-9_][A-Za-z0-9._~-]{0,127}(?:\/conversations\/[A-Za-z0-9_][A-Za-z0-9._~-]{0,127})?$/.test(path);
}

function scalar(value: unknown): string {
  const text = typeof value === "string" ? value.trim() : "";
  return IDENTIFIER.test(text) ? text : "";
}

function safeErrorCode(value: string): string {
  return /^[a-z][a-z0-9_]{0,63}$/.test(value) ? value : "browser_ticket_failed";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
