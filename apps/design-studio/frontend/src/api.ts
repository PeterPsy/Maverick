import type { OpenDesignNavigateMessage, OpenDesignNavigation, OpenDesignOpenSettingsMessage, OpenDesignThemeMessage, SidecarLaunch } from "./types";

const PROJECT_ID_PATTERN = /^[A-Za-z0-9_][A-Za-z0-9._~-]{0,127}$/;
const RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
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

export async function requestOpenDesignLaunch(
  appId: string,
  navigation: OpenDesignNavigation,
  platformOrigin = window.location.origin,
): Promise<SidecarLaunch> {
  const response = await fetch("/api/app-sidecars/browser-launch", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
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
      : "sidecar_launch_failed";
    throw new SidecarLaunchError(code, response.status);
  }
  return validateSidecarLaunch(payload, platformOrigin);
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
  return /^[a-z][a-z0-9_]{0,63}$/.test(value) ? value : "sidecar_launch_failed";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
