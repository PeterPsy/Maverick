import {
  forwardRef,
  useEffect,
  useRef,
  type IframeHTMLAttributes,
  type MutableRefObject,
  type Ref,
} from "react";

import { setMaverickFrameOrigin } from "../iframePolicy";

const APP_FRAME_LAUNCH_PATH = "/api/app-frames/browser-launch";

type IsolatedAppFrameLaunch = {
  bootstrap_url: string;
  method: "POST";
  mode?: "isolated";
  origin: string;
  ticket: string;
  ticket_field: "ticket";
};

type SameOriginAppFrameLaunch = {
  launch_url: string;
  mode: "same_origin";
  origin: string;
};

type AppFrameLaunch = IsolatedAppFrameLaunch | SameOriginAppFrameLaunch;

type RawLaunchPayload = {
  bootstrap_url?: string;
  error?: unknown;
  launch_url?: string;
  method?: string;
  mode?: string;
  origin?: string;
  ticket?: string;
  ticket_field?: string;
};

type IsolatedMaverickFrameProps = Omit<IframeHTMLAttributes<HTMLIFrameElement>, "name" | "src"> & {
  appId: string;
  launchPath: string;
  onLaunchError?: (error: Error) => void;
};

export const IsolatedMaverickFrame = forwardRef<HTMLIFrameElement, IsolatedMaverickFrameProps>(
  function IsolatedMaverickFrame({ appId, launchPath, onLoad, onLaunchError, ...iframeProps }, forwardedRef) {
    const frameRef = useRef<HTMLIFrameElement | null>(null);
    const frameNameRef = useRef(`maverick-app-frame-${crypto.randomUUID()}`);

    useEffect(() => {
      const frame = frameRef.current;
      if (!frame) return;
      const controller = new AbortController();
      let armTimer: number | undefined;
      setMaverickFrameOrigin(frame, null);
      delete frame.dataset.maverickFrameBootstrapArmed;
      void requestAppFrameLaunch(appId, launchPath, controller.signal)
        .then((launch) => {
          if (controller.signal.aborted || frameRef.current !== frame) return;
          setMaverickFrameOrigin(frame, launch.origin, launch.mode === "same_origin");
          if (launch.mode === "same_origin") {
            frame.src = launch.launch_url;
            frame.dataset.maverickFrameBootstrapArmed = "true";
          } else {
            submitBootstrapForm(frame, launch);
            armTimer = window.setTimeout(() => {
              frame.dataset.maverickFrameBootstrapArmed = "true";
            }, 0);
          }
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setMaverickFrameOrigin(frame, null);
          onLaunchError?.(error instanceof Error ? error : new Error("Unable to launch isolated app frame."));
        });
      return () => {
        controller.abort();
        if (armTimer !== undefined) window.clearTimeout(armTimer);
        delete frame.dataset.maverickFrameBootstrapArmed;
        setMaverickFrameOrigin(frame, null);
      };
    }, [appId, launchPath, onLaunchError]);

    return (
      <iframe
        {...iframeProps}
        name={frameNameRef.current}
        onLoad={(event) => {
          if (isolatedNavigationLoaded(event.currentTarget)) onLoad?.(event);
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
  const payload = (await response.json().catch(() => ({}))) as RawLaunchPayload;
  if (!response.ok) {
    throw new Error(typeof payload.error === "string" ? payload.error : "Unable to launch isolated app frame.");
  }
  const origin = exactOrigin(payload.origin);
  if (payload.mode === "same_origin") {
    const launchUrl = typeof payload.launch_url === "string" && payload.launch_url.startsWith("/")
      ? payload.launch_url
      : launchPath;
    return {
      launch_url: launchUrl,
      mode: "same_origin",
      origin: window.location.origin,
    };
  }
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
    mode: "isolated",
    origin,
    ticket,
    ticket_field: "ticket",
  };
}

function submitBootstrapForm(frame: HTMLIFrameElement, launch: IsolatedAppFrameLaunch) {
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

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (typeof ref === "function") {
    ref(value);
    return;
  }
  if (ref) (ref as MutableRefObject<T | null>).current = value;
}
