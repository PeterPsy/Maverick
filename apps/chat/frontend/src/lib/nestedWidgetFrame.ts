import { requestJson } from "../api/http";
import type { WidgetRegistryItem } from "../api/types";

export const NESTED_WIDGET_BROWSER_LAUNCH_PATH = "/api/apps/widgets/browser-launch";
export const NESTED_WIDGET_LOADED_MESSAGE = "maverick.app-frame.loaded";
export const NESTED_WIDGET_LOAD_TIMEOUT_MS = 10_000;

const NESTED_WIDGET_BOOTSTRAP_PATH = "/.well-known/maverick-app-frame-bootstrap";

export type NestedWidgetLaunch = {
  bootstrapUrl: string;
  expiresInSeconds: number;
  hostAppId: string;
  origin: string;
  ownerAppId: string;
  parentOrigin: string;
  targetUrl: string;
  ticket: string;
  widgetId: string;
};

export async function requestNestedWidgetLaunch(
  widget: WidgetRegistryItem,
  contextToken: string,
  parentOrigin = window.location.origin,
): Promise<NestedWidgetLaunch> {
  const payload = await requestJson<unknown>(NESTED_WIDGET_BROWSER_LAUNCH_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      context_token: contextToken,
      frontend_path: widget.frontend_mount,
      owner_app_id: widget.owner_app_id,
      widget_id: widget.widget_id,
    }),
  });
  return validateNestedWidgetLaunch(payload, widget, parentOrigin, contextToken);
}

export function validateNestedWidgetLaunch(
  payload: unknown,
  widget: WidgetRegistryItem,
  parentOrigin: string,
  contextToken: string,
): NestedWidgetLaunch {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Invalid nested widget launch response.");
  }
  const record = payload as Record<string, unknown>;
  const origin = exactHttpOrigin(record.origin);
  const normalizedParentOrigin = exactHttpOrigin(parentOrigin);
  const bootstrapUrl = exactBootstrapUrl(record.bootstrap_url, origin);
  const targetUrl = exactFrontendUrl(record.frontend_url, origin, widget.frontend_mount, contextToken);
  const ticket = boundedOpaqueString(record.ticket, 1024);
  const expiresInSeconds = record.expires_in_seconds;
  if (
    origin === normalizedParentOrigin
    || origin === configuredPlatformOrigin()
    || record.parent_origin !== normalizedParentOrigin
    || record.bootstrap_transport !== "cors"
    || record.host_app_id !== widget.host
    || record.owner_app_id !== widget.owner_app_id
    || record.widget_id !== widget.widget_id
    || record.method !== "POST"
    || record.ticket_field !== "ticket"
    || !ticket
    || typeof expiresInSeconds !== "number"
    || !Number.isInteger(expiresInSeconds)
    || expiresInSeconds <= 0
    || expiresInSeconds > 3600
  ) {
    throw new Error("Nested widget launch attestation failed.");
  }
  return {
    bootstrapUrl,
    expiresInSeconds,
    hostAppId: widget.host,
    origin,
    ownerAppId: widget.owner_app_id,
    parentOrigin: normalizedParentOrigin,
    targetUrl,
    ticket,
    widgetId: widget.widget_id,
  };
}

export function submitNestedWidgetBootstrap(
  frame: HTMLIFrameElement,
  launch: NestedWidgetLaunch,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  return fetchImpl(launch.bootstrapUrl, {
    body: new URLSearchParams({ ticket: launch.ticket }).toString(),
    cache: "no-store",
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    },
    method: "POST",
    mode: "cors",
    redirect: "error",
    referrerPolicy: "no-referrer",
  }).then((response) => {
    if (!response.ok || response.status !== 204) {
      throw new Error("Nested widget bootstrap failed.");
    }
    frame.setAttribute("src", launch.targetUrl);
  });
}

function exactFrontendUrl(
  value: unknown,
  origin: string,
  frontendMount: string,
  contextToken: string,
): string {
  if (typeof value !== "string" || !contextToken) {
    throw new Error("Nested widget frontend URL is invalid.");
  }
  let parsed: URL;
  let expected: URL;
  try {
    parsed = new URL(value);
    expected = new URL(frontendMount, origin);
  } catch {
    throw new Error("Nested widget frontend URL is invalid.");
  }
  const fragment = parsed.hash.startsWith("#") ? parsed.hash.slice(1) : "";
  const parameters = new URLSearchParams(fragment);
  if (
    parsed.origin !== origin
    || parsed.username
    || parsed.password
    || parsed.pathname !== expected.pathname
    || parsed.search !== expected.search
    || expected.hash
    || [...parameters.keys()].length !== 1
    || parameters.get("context") !== contextToken
  ) {
    throw new Error("Nested widget frontend URL is invalid.");
  }
  return parsed.href;
}

export function isNestedWidgetLoadedMessage(
  event: MessageEvent,
  frame: HTMLIFrameElement | null,
  launch: NestedWidgetLaunch,
): boolean {
  if (
    event.origin !== launch.origin
    || event.source !== frame?.contentWindow
    || !event.data
    || typeof event.data !== "object"
  ) {
    return false;
  }
  const payload = event.data as Record<string, unknown>;
  return (
    payload.type === NESTED_WIDGET_LOADED_MESSAGE
    && payload.owner_app_id === launch.ownerAppId
    && payload.widget_id === launch.widgetId
  );
}

function exactHttpOrigin(value: unknown): string {
  if (typeof value !== "string" || !value) {
    throw new Error("Nested widget launch origin is invalid.");
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("Nested widget launch origin is invalid.");
  }
  if (
    !["http:", "https:"].includes(parsed.protocol)
    || parsed.username
    || parsed.password
    || parsed.pathname !== "/"
    || parsed.search
    || parsed.hash
    || parsed.origin !== value
  ) {
    throw new Error("Nested widget launch origin is invalid.");
  }
  return parsed.origin;
}

function exactBootstrapUrl(value: unknown, origin: string): string {
  if (typeof value !== "string") {
    throw new Error("Nested widget bootstrap URL is invalid.");
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("Nested widget bootstrap URL is invalid.");
  }
  if (
    parsed.origin !== origin
    || parsed.pathname !== NESTED_WIDGET_BOOTSTRAP_PATH
    || parsed.search
    || parsed.hash
    || parsed.username
    || parsed.password
  ) {
    throw new Error("Nested widget bootstrap URL is invalid.");
  }
  return parsed.href;
}

function boundedOpaqueString(value: unknown, maximum: number): string {
  if (
    typeof value !== "string"
    || !value
    || value.length > maximum
    || /[\s\u0000-\u001f\u007f]/u.test(value)
  ) {
    return "";
  }
  return value;
}

function configuredPlatformOrigin(): string {
  const candidate = (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: unknown })
    .__MAVERICK_PLATFORM_ORIGIN__;
  if (typeof candidate !== "string") {
    return "";
  }
  try {
    return exactHttpOrigin(candidate);
  } catch {
    return "";
  }
}
