import type { OpenDesignLaunchTarget, OpenDesignNavigateMessage, OpenDesignNavigation, OpenDesignOpenSettingsMessage, OpenDesignOpenToolsMessage, OpenDesignThemeMessage, SidecarLaunch } from "./types";

const PROJECT_ID_PATTERN = /^[A-Za-z0-9_][A-Za-z0-9._~-]{0,127}$/;
const RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const BOOTSTRAP_PATH = "/.well-known/maverick-sidecar-bootstrap";
const LAUNCH_TARGET_CACHE_PREFIX = "maverick:design-studio:launch-target:v1";

export class SidecarLaunchError extends Error {
  readonly code: string;
  readonly status: number;
  readonly phase: string;
  readonly autoRepairable: boolean;
  readonly retryable: boolean;

  constructor(
    code: string,
    status: number,
    phase = "launch",
    autoRepairable = false,
    retryable = launchErrorIsRetryable(code, autoRepairable),
  ) {
    super("OpenDesign could not be opened through its governed browser origin.");
    this.name = "SidecarLaunchError";
    this.code = code;
    this.status = status;
    this.phase = phase;
    this.autoRepairable = autoRepairable;
    this.retryable = retryable;
  }
}

export function currentDesignStudioAppId(pathname = window.location.pathname): string {
  const match = /^\/apps\/([^/?#]+)/.exec(pathname);
  return match?.[1] || "design-studio";
}

export function navigationFromParams(
  params: Record<string, string | boolean | null | undefined>,
): OpenDesignNavigation {
  return {
    od_project_id: validScalar(params.od_project_id ?? params.project_id, PROJECT_ID_PATTERN),
    od_run_id: validScalar(params.od_run_id ?? params.run_id, RUN_ID_PATTERN),
  };
}

export function initialNavigation(search = window.location.search): OpenDesignNavigation {
  return navigationFromParams(Object.fromEntries(new URLSearchParams(search).entries()));
}

export function openDesignPath(navigation: OpenDesignNavigation): string {
  return navigation.od_project_id
    ? `/projects/${encodeURIComponent(navigation.od_project_id)}`
    : "/index.html";
}

export function readCachedLaunchTarget(
  storage: Pick<Storage, "getItem" | "removeItem">,
  appId: string,
  sidecarOrigin: string,
): OpenDesignLaunchTarget | null {
  const key = launchTargetCacheKey(appId, sidecarOrigin);
  try {
    const payload = JSON.parse(storage.getItem(key) || "null") as unknown;
    if (!isRecord(payload)) {
      return null;
    }
    const target = payload.target;
    const projectId = validScalar(payload.od_project_id as string | undefined, PROJECT_ID_PATTERN);
    if (target === "empty" && !projectId) {
      return { target: "empty", od_project_id: "", project: null };
    }
    if (target === "project" && projectId) {
      return { target: "project", od_project_id: projectId, project: { id: projectId } };
    }
  } catch {
    // Invalid or unavailable session storage is a cache miss.
  }
  try {
    storage.removeItem(key);
  } catch {}
  return null;
}

export function writeCachedLaunchTarget(
  storage: Pick<Storage, "setItem">,
  appId: string,
  sidecarOrigin: string,
  target: OpenDesignLaunchTarget,
): void {
  const normalized = target.target === "project"
    ? navigationFromParams({ od_project_id: target.od_project_id }).od_project_id
    : "";
  if ((target.target === "project" && !normalized) || (target.target === "empty" && target.od_project_id)) {
    return;
  }
  try {
    storage.setItem(
      launchTargetCacheKey(appId, sidecarOrigin),
      JSON.stringify({ target: target.target, od_project_id: normalized }),
    );
  } catch {
    // Launch remains authoritative when browser storage is unavailable.
  }
}

export async function requestOpenDesignLaunch(
  appId: string,
  navigation: OpenDesignNavigation,
  platformOrigin = window.location.origin,
  signal?: AbortSignal,
): Promise<SidecarLaunch> {
  const response = await fetch("/api/app-sidecars/browser-launch", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify({
      app_id: appId,
      sidecar_id: "opendesign",
      path: openDesignPath(navigation),
    }),
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
    const phase = isRecord(payload) && typeof payload.phase === "string"
      ? safeErrorCode(payload.phase)
      : "launch";
    const autoRepairable = isRecord(payload) && payload.auto_repairable === true;
    const retryable = isRecord(payload) && typeof payload.retryable === "boolean"
      ? payload.retryable
      : launchErrorIsRetryable(code, autoRepairable);
    throw new SidecarLaunchError(code, response.status, phase, autoRepairable, retryable);
  }
  return validateSidecarLaunch(payload, platformOrigin);
}

export function launchErrorIsRetryable(code: string, autoRepairable = false): boolean {
  return autoRepairable || new Set([
    "artifact_repairing",
    "browser_ticket_failed",
    "daemon_ready_timeout",
    "daemon_spawn_failed",
    "activation_incomplete",
    "sidecar_frame_load_failed",
    "sidecar_origin_unavailable",
  ]).has(code);
}

export function validateSidecarLaunch(payload: unknown, platformOrigin: string): SidecarLaunch {
  if (!isRecord(payload)) {
    throw new SidecarLaunchError("sidecar_launch_response_invalid", 502);
  }
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
  let isolatedOrigin: URL;
  let bootstrap: URL;
  let platform: URL;
  try {
    isolatedOrigin = new URL(candidate.origin);
    bootstrap = new URL(candidate.bootstrap_url);
    platform = new URL(platformOrigin);
  } catch {
    throw new SidecarLaunchError("sidecar_launch_response_invalid", 502);
  }
  if (
    !["http:", "https:"].includes(isolatedOrigin.protocol)
    || isolatedOrigin.origin !== candidate.origin
    || isolatedOrigin.username
    || isolatedOrigin.password
    || isolatedOrigin.origin === platform.origin
    || bootstrap.origin !== isolatedOrigin.origin
    || bootstrap.pathname !== BOOTSTRAP_PATH
    || bootstrap.search
    || bootstrap.hash
  ) {
    throw new SidecarLaunchError("sidecar_launch_response_invalid", 502);
  }
  return candidate as SidecarLaunch;
}

export function navigationMessage(navigation: OpenDesignNavigation): OpenDesignNavigateMessage {
  return {
    type: "maverick.opendesign.navigate",
    version: 1,
    ...(navigation.od_project_id ? { od_project_id: navigation.od_project_id } : {}),
    ...(navigation.od_run_id ? { od_run_id: navigation.od_run_id } : {}),
  };
}

export function themeMessage(theme: "dark" | "light"): OpenDesignThemeMessage {
  return { type: "maverick.opendesign.theme", version: 1, theme };
}

export function openSettingsMessage(): OpenDesignOpenSettingsMessage {
  return { type: "maverick.opendesign.open-settings", version: 1 };
}

export function openToolsMessage(requestId: string): OpenDesignOpenToolsMessage {
  return { type: "maverick.opendesign.open-tools", version: 1, request_id: requestId };
}

export function isTrustedSidecarMessage(
  event: Pick<MessageEvent, "origin" | "source">,
  expectedOrigin: string,
  expectedSource: Window | null,
): boolean {
  return Boolean(expectedOrigin && event.origin === expectedOrigin && expectedSource && event.source === expectedSource);
}

function validScalar(value: string | boolean | null | undefined, pattern: RegExp): string {
  const text = typeof value === "string" ? value.trim() : "";
  return pattern.test(text) ? text : "";
}

function safeErrorCode(value: string): string {
  return /^[a-z][a-z0-9_]{0,63}$/.test(value) ? value : "browser_ticket_failed";
}

function launchTargetCacheKey(appId: string, sidecarOrigin: string): string {
  return `${LAUNCH_TARGET_CACHE_PREFIX}:${encodeURIComponent(appId)}:${encodeURIComponent(sidecarOrigin)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
