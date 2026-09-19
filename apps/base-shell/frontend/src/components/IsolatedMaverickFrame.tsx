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
import type { ShellEffectiveTheme } from "../theme";

const APP_FRAME_LAUNCH_PATH = "/api/app-frames/browser-launch";
const APP_FRAME_BOOTSTRAP_MESSAGE = "maverick.app-frame.bootstrap";
const APP_FRAME_BOOTSTRAP_SUBMITTED_MESSAGE = "maverick.app-frame.bootstrap-submitted";
export const APP_FRAME_AUTHORIZATION_REQUIRED_MESSAGE = "maverick.app-frame.authorization-required";

type AppFrameLaunch = {
  bootstrap_url: string;
  method: "POST";
  origin: string;
  ticket: string;
  ticket_field: "ticket";
};

type PendingAppFrameLaunch = {
  bootstrapId: string;
  launch: AppFrameLaunch;
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
  loadingTheme?: ShellEffectiveTheme;
  onLaunchError?: (error: Error) => void;
};

export const IsolatedMaverickFrame = forwardRef<HTMLIFrameElement, IsolatedMaverickFrameProps>(
  function IsolatedMaverickFrame({
    appId,
    frameScope,
    launchPath,
    loadingTheme = "dark",
    onLoad,
    onLaunchError,
    ...iframeProps
  }, forwardedRef) {
    const frameRef = useRef<HTMLIFrameElement | null>(null);
    const frameNameRef = useRef(`maverick-app-frame-${crypto.randomUUID()}`);
    const bootstrapPendingRef = useRef(false);
    const pendingLaunchRef = useRef<PendingAppFrameLaunch | null>(null);
    const activeBootstrapIdRef = useRef<string | null>(null);
    const loadingThemeRef = useRef(loadingTheme);
    const loadingDocumentRef = useRef(maverickLoadingDocument(loadingTheme, crypto.randomUUID()));
    loadingThemeRef.current = loadingTheme;

    useEffect(() => {
      const frame = frameRef.current;
      if (!frame) return;
      let activeController: AbortController | null = null;
      bootstrapPendingRef.current = false;
      pendingLaunchRef.current = null;
      activeBootstrapIdRef.current = null;
      setMaverickFrameOrigin(frame, null, appId, frameScope);
      delete frame.dataset.maverickFrameBootstrapArmed;

      const launchFrame = (requestedPath: string, preserveCurrentOrigin: boolean) => {
        if (activeController) return;
        const controller = new AbortController();
        activeController = controller;
        void requestAppFrameLaunch(appId, requestedPath, controller.signal)
          .then((launch) => {
            if (controller.signal.aborted || frameRef.current !== frame) return;
            delete frame.dataset.maverickFrameBootstrapArmed;
            setMaverickFrameOrigin(frame, launch.origin, appId, frameScope);
            bootstrapPendingRef.current = true;
            const bootstrapId = crypto.randomUUID();
            activeBootstrapIdRef.current = bootstrapId;
            pendingLaunchRef.current = { bootstrapId, launch };
            frame.srcdoc = maverickLoadingDocument(loadingThemeRef.current, bootstrapId);
          })
          .catch((error: unknown) => {
            if (controller.signal.aborted || frameRef.current !== frame) return;
            bootstrapPendingRef.current = false;
            pendingLaunchRef.current = null;
            activeBootstrapIdRef.current = null;
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

      const handleBootstrapSubmitted = (event: MessageEvent) => {
        if (event.source !== frame.contentWindow || !event.data || typeof event.data !== "object") return;
        if (event.origin !== window.location.origin && event.origin !== "null") return;
        const data = event.data as { bootstrap_id?: unknown; type?: unknown };
        if (
          data.type !== APP_FRAME_BOOTSTRAP_SUBMITTED_MESSAGE
          || typeof data.bootstrap_id !== "string"
          || data.bootstrap_id !== activeBootstrapIdRef.current
        ) return;
        frame.dataset.maverickFrameBootstrapArmed = "true";
      };

      window.addEventListener("message", handleAuthorizationRequired);
      window.addEventListener("message", handleBootstrapSubmitted);
      launchFrame(launchPath, false);
      return () => {
        window.removeEventListener("message", handleAuthorizationRequired);
        window.removeEventListener("message", handleBootstrapSubmitted);
        activeController?.abort();
        bootstrapPendingRef.current = false;
        pendingLaunchRef.current = null;
        activeBootstrapIdRef.current = null;
        delete frame.dataset.maverickFrameBootstrapArmed;
        setMaverickFrameOrigin(frame, null, appId, frameScope);
      };
    }, [appId, frameScope, launchPath, onLaunchError]);

    return (
      <iframe
        {...iframeProps}
        name={frameNameRef.current}
        onLoad={(event) => {
          const frame = event.currentTarget;
          const pendingLaunch = pendingLaunchRef.current;
          if (pendingLaunch) {
            pendingLaunchRef.current = null;
            try {
              postBootstrapLaunch(frame, pendingLaunch);
            } catch (error) {
              bootstrapPendingRef.current = false;
              activeBootstrapIdRef.current = null;
              delete frame.dataset.maverickFrameBootstrapArmed;
              onLaunchError?.(error instanceof Error ? error : new Error("Unable to bootstrap isolated app frame."));
            }
            return;
          }
          if (isolatedNavigationLoaded(frame)) {
            bootstrapPendingRef.current = false;
            activeBootstrapIdRef.current = null;
            onLoad?.(event);
          }
        }}
        ref={(frame) => {
          frameRef.current = frame;
          assignRef(forwardedRef, frame);
        }}
        srcDoc={loadingDocumentRef.current}
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

function postBootstrapLaunch(frame: HTMLIFrameElement, pending: PendingAppFrameLaunch) {
  if (!frame.contentWindow) throw new Error("The isolated app frame is not ready for bootstrap.");
  frame.contentWindow.postMessage({
    bootstrap_id: pending.bootstrapId,
    launch: pending.launch,
    type: APP_FRAME_BOOTSTRAP_MESSAGE,
  }, "*");
}

function maverickLoadingDocument(theme: ShellEffectiveTheme, revision: string): string {
  const background = theme === "light" ? "#f7f8fb" : "#070708";
  const accent = theme === "light" ? "#0f172a" : "#ffffff";
  const parentOrigin = JSON.stringify(window.location.origin);
  return `<!doctype html><html data-maverick-loader="${revision}" style="color-scheme:${theme};background:${background}"><head><meta charset="utf-8"><meta name="color-scheme" content="${theme}"><style>html,body{width:100%;height:100%;margin:0;background:${background}}body{display:grid;place-items:center}.m{width:22px;height:22px;background:${accent};animation:m 1.6s ease-in-out infinite}@keyframes m{0%,100%{border-radius:50%;transform:scale(.82) rotate(0)}50%{border-radius:18%;transform:scale(1) rotate(135deg)}}</style><script>(()=>{const parentOrigin=${parentOrigin};const bootstrapId="${revision}";let submitted=false;addEventListener("message",event=>{if(submitted||event.source!==parent||event.origin!==parentOrigin)return;const message=event.data;const launch=message&&message.type==="${APP_FRAME_BOOTSTRAP_MESSAGE}"&&message.bootstrap_id===bootstrapId&&message.launch;if(!launch||launch.method!=="POST"||launch.ticket_field!=="ticket"||typeof launch.bootstrap_url!=="string"||typeof launch.origin!=="string"||typeof launch.ticket!=="string"||!launch.ticket||launch.ticket.length>512||/\\s/u.test(launch.ticket))return;let action;try{action=new URL(launch.bootstrap_url)}catch{return}if(action.origin!==launch.origin)return;submitted=true;const form=document.createElement("form");form.action=action.href;form.method="POST";form.target="_self";form.hidden=true;const ticket=document.createElement("input");ticket.name="ticket";ticket.type="hidden";ticket.value=launch.ticket;form.append(ticket);document.body.append(form);parent.postMessage({bootstrap_id:bootstrapId,type:"${APP_FRAME_BOOTSTRAP_SUBMITTED_MESSAGE}"},parentOrigin);form.submit()})})();</script></head><body><span class="m" aria-hidden="true"></span></body></html>`;
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
