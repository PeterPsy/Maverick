import {
  forwardRef,
  useEffect,
  useRef,
  type IframeHTMLAttributes,
  type MutableRefObject,
  type Ref,
} from "react";

import {
  isMaverickFrameMessage,
  setMaverickFrameOrigin,
  type MaverickFrameScope,
} from "../iframePolicy";
import { revokeShellAuthorization } from "../pwaCacheRuntime";

const APP_FRAME_LAUNCH_PATH = "/api/app-frames/browser-launch";
export const APP_FRAME_AUTHORIZATION_REQUIRED_MESSAGE = "maverick.app-frame.authorization-required";

type AppFrameLaunch = {
  bootstrap_url: string;
  method: "POST";
  origin: string;
  ticket: string;
  ticket_field: "ticket";
};

type RawLaunchPayload = {
  bootstrap_url?: string;
  error?: unknown;
  method?: string;
  origin?: string;
  ticket?: string;
  ticket_field?: string;
};

type IsolatedMaverickFrameProps = Omit<IframeHTMLAttributes<HTMLIFrameElement>, "name" | "src"> & {
  appId: string;
  frameScope: MaverickFrameScope;
  launchPath: string;
  onLaunchError?: (error: Error) => void;
};

export const IsolatedMaverickFrame = forwardRef<HTMLIFrameElement, IsolatedMaverickFrameProps>(
  function IsolatedMaverickFrame({ appId, frameScope, launchPath, onLoad, onLaunchError, ...iframeProps }, forwardedRef) {
    const frameRef = useRef<HTMLIFrameElement | null>(null);
    const frameNameRef = useRef(`maverick-app-frame-${crypto.randomUUID()}`);
    const bootstrapPendingRef = useRef(false);

    useEffect(() => {
      const frame = frameRef.current;
      if (!frame) return;
      let activeController: AbortController | null = null;
      let armTimer: number | undefined;
      bootstrapPendingRef.current = false;
      setMaverickFrameOrigin(frame, null, appId, frameScope);
      delete frame.dataset.maverickFrameBootstrapArmed;

      const launchFrame = (requestedPath: string, preserveCurrentOrigin: boolean) => {
        if (activeController) return;
        const controller = new AbortController();
        activeController = controller;
        void requestAppFrameLaunch(appId, requestedPath, controller.signal)
          .then((launch) => {
            if (controller.signal.aborted || frameRef.current !== frame) return;
            if (armTimer !== undefined) window.clearTimeout(armTimer);
            delete frame.dataset.maverickFrameBootstrapArmed;
            setMaverickFrameOrigin(frame, launch.origin, appId, frameScope);
            bootstrapPendingRef.current = true;
            try {
              submitBootstrapForm(frame, launch);
            } catch (error) {
              bootstrapPendingRef.current = false;
              throw error;
            }
            armTimer = window.setTimeout(() => {
              frame.dataset.maverickFrameBootstrapArmed = "true";
            }, 0);
          })
          .catch((error: unknown) => {
            if (controller.signal.aborted || frameRef.current !== frame) return;
            if (!preserveCurrentOrigin) setMaverickFrameOrigin(frame, null, appId, frameScope);
            onLaunchError?.(error instanceof Error ? error : new Error("Unable to launch isolated app frame."));
          })
          .finally(() => {
            if (activeController === controller) activeController = null;
          });
      };

      const handleAuthorizationRequired = (event: MessageEvent) => {
        if (bootstrapPendingRef.current || !isAppFrameAuthorizationRequiredMessage(event, frame)) return;
        launchFrame(recoveryLaunchPath(event.data, launchPath), true);
      };

      window.addEventListener("message", handleAuthorizationRequired);
      launchFrame(launchPath, false);
      return () => {
        window.removeEventListener("message", handleAuthorizationRequired);
        activeController?.abort();
        bootstrapPendingRef.current = false;
        if (armTimer !== undefined) window.clearTimeout(armTimer);
        delete frame.dataset.maverickFrameBootstrapArmed;
        setMaverickFrameOrigin(frame, null, appId, frameScope);
      };
    }, [appId, frameScope, launchPath, onLaunchError]);

    return (
      <iframe
        {...iframeProps}
        name={frameNameRef.current}
        onLoad={(event) => {
          if (isolatedNavigationLoaded(event.currentTarget)) {
            bootstrapPendingRef.current = false;
            onLoad?.(event);
          }
        }}
        ref={(frame) => {
          frameRef.current = frame;
          assignRef(forwardedRef, frame);
        }}
        src="about:blank"
      />
    );
  },
);

export function isAppFrameAuthorizationRequiredMessage(
  event: MessageEvent,
  frame: HTMLIFrameElement | null | undefined,
): boolean {
  if (!isMaverickFrameMessage(event, frame) || !event.data || typeof event.data !== "object") return false;
  return (event.data as { type?: unknown }).type === APP_FRAME_AUTHORIZATION_REQUIRED_MESSAGE;
}

export async function requestAppFrameLaunch(
  appId: string,
  launchPath: string,
  signal?: AbortSignal,
): Promise<AppFrameLaunch> {
  const response = await fetch(APP_FRAME_LAUNCH_PATH, {
    body: JSON.stringify({ app_id: appId, path: launchPath }),
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    method: "POST",
    signal,
  });
  if (!response.ok && (response.status === 401 || response.status === 403)) {
    void revokeShellAuthorization(response.status);
  }
  const payload = (await response.json().catch(() => ({}))) as RawLaunchPayload;
  if (!response.ok) {
    throw new Error(typeof payload.error === "string" ? payload.error : "Unable to launch isolated app frame.");
  }
  const origin = exactOrigin(payload.origin);
  if (!origin || origin === window.location.origin) {
    throw new Error("Core returned an invalid isolated app-frame launch.");
  }
  const bootstrap = new URL(String(payload.bootstrap_url || ""));
  const ticket = String(payload.ticket || "");
  if (
    bootstrap.origin !== origin
    || payload.method !== "POST"
    || payload.ticket_field !== "ticket"
    || !ticket
    || ticket.length > 512
    || /\s/u.test(ticket)
  ) {
    throw new Error("Core returned an invalid isolated app-frame launch.");
  }
  return {
    bootstrap_url: bootstrap.href,
    method: "POST",
    origin,
    ticket,
    ticket_field: "ticket",
  };
}

function submitBootstrapForm(frame: HTMLIFrameElement, launch: AppFrameLaunch) {
  const form = document.createElement("form");
  form.action = launch.bootstrap_url;
  form.method = launch.method;
  form.target = frame.name;
  form.hidden = true;
  const ticket = document.createElement("input");
  ticket.name = launch.ticket_field;
  ticket.type = "hidden";
  ticket.value = launch.ticket;
  form.append(ticket);
  document.body.append(form);
  try {
    form.submit();
  } finally {
    form.remove();
  }
}

function isolatedNavigationLoaded(frame: HTMLIFrameElement): boolean {
  return Boolean(
    frame.contentWindow
    && frame.dataset.maverickFrameOrigin
    && frame.dataset.maverickFrameBootstrapArmed === "true",
  );
}

function exactOrigin(value: unknown): string | null {
  if (typeof value !== "string" || !value) return null;
  try {
    const parsed = new URL(value);
    return parsed.origin === value && ["http:", "https:"].includes(parsed.protocol) ? parsed.origin : null;
  } catch {
    return null;
  }
}

function recoveryLaunchPath(data: unknown, fallback: string): string {
  if (!data || typeof data !== "object") return fallback;
  const path = (data as { path?: unknown }).path;
  return typeof path === "string"
    && path.length <= 4096
    && path.startsWith("/")
    && !path.startsWith("//")
    && !/[\\\u0000-\u001f]/u.test(path)
    ? path
    : fallback;
}

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (typeof ref === "function") {
    ref(value);
    return;
  }
  if (ref) (ref as MutableRefObject<T | null>).current = value;
}
