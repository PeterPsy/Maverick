import { useCallback, useEffect, useRef, useState } from "react";
import { Expand, LoaderCircle, RefreshCw, TriangleAlert } from "lucide-react";
import {
  currentDesignStudioAppId,
  initialNavigation,
  isTrustedSidecarMessage,
  navigationFromParams,
  navigationMessage,
  requestOpenDesignLaunch,
  SidecarLaunchError,
} from "./api";
import type { OpenDesignNavigation, SidecarDiagnostic, SidecarHostPhase, SidecarLaunch } from "./types";
import "./styles/main.css";

const LOAD_DEGRADED_AFTER_MS = 20_000;

export function App() {
  const appId = currentDesignStudioAppId();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const frameNameRef = useRef(`opendesign-${crypto.randomUUID()}`);
  const submittedFrameRef = useRef<HTMLIFrameElement | null>(null);
  const sidecarOriginRef = useRef("");
  const navigationRef = useRef<OpenDesignNavigation>(initialNavigation());
  const [navigation, setNavigation] = useState(navigationRef.current);
  const [phase, setPhase] = useState<SidecarHostPhase>("launching");
  const [diagnostic, setDiagnostic] = useState<SidecarDiagnostic | null>(null);
  const [launchRevision, setLaunchRevision] = useState(0);

  const postNavigation = useCallback(() => {
    const frameWindow = frameRef.current?.contentWindow;
    const origin = sidecarOriginRef.current;
    if (!frameWindow || !origin) {
      return;
    }
    frameWindow.postMessage(navigationMessage(navigationRef.current), origin);
  }, []);

  useEffect(() => {
    window.parent?.postMessage({ type: "maverick.app.ready", app_id: appId }, window.location.origin);
  }, [appId]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin === window.location.origin && event.source === window.parent && isRecord(event.data)) {
        if (event.data.type !== "maverick.app.navigate") {
          return;
        }
        if (event.data.app_id && event.data.app_id !== appId) {
          return;
        }
        const params = isRecord(event.data.params)
          ? event.data.params as Record<string, string | boolean | null>
          : {};
        const next = navigationFromParams(params);
        if (next.od_project_id === navigationRef.current.od_project_id && next.od_run_id === navigationRef.current.od_run_id) {
          return;
        }
        navigationRef.current = next;
        setNavigation(next);
        setLaunchRevision((value) => value + 1);
        return;
      }
      const frameWindow = frameRef.current?.contentWindow || null;
      if (!isTrustedSidecarMessage(event, sidecarOriginRef.current, frameWindow) || !isRecord(event.data)) {
        return;
      }
      if (event.data.type === "maverick.opendesign.ready" && event.data.version === 1) {
        setDiagnostic(null);
        setPhase("ready");
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [appId]);

  useEffect(() => {
    let canceled = false;
    let degradedTimer = 0;
    const frame = frameRef.current;
    submittedFrameRef.current = null;
    sidecarOriginRef.current = "";
    setDiagnostic(null);
    setPhase("launching");

    void requestOpenDesignLaunch(appId, navigation)
      .then((launch) => {
        if (canceled || !frame) {
          return;
        }
        sidecarOriginRef.current = launch.origin;
        setPhase("bootstrapping");
        submittedFrameRef.current = frame;
        submitBootstrapForm(frame, launch);
        degradedTimer = window.setTimeout(() => {
          setPhase((current) => {
            if (current !== "bootstrapping") {
              return current;
            }
            setDiagnostic({ code: "sidecar_load_delayed", status: 0 });
            return "degraded";
          });
        }, LOAD_DEGRADED_AFTER_MS);
      })
      .catch((error: unknown) => {
        if (canceled) {
          return;
        }
        const launchError = error instanceof SidecarLaunchError
          ? error
          : new SidecarLaunchError("sidecar_launch_failed", 0);
        setDiagnostic({ code: launchError.code, status: launchError.status });
        setPhase("error");
      });

    return () => {
      canceled = true;
      window.clearTimeout(degradedTimer);
    };
  }, [appId, launchRevision, navigation]);

  function handleFrameLoad() {
    if (submittedFrameRef.current !== frameRef.current) {
      return;
    }
    setDiagnostic(null);
    setPhase("ready");
    postNavigation();
  }

  function handleFrameError() {
    if (submittedFrameRef.current !== frameRef.current) {
      return;
    }
    setDiagnostic({ code: "sidecar_frame_load_failed", status: 0 });
    setPhase("error");
  }

  function retry() {
    setLaunchRevision((value) => value + 1);
  }

  async function enterFullscreen() {
    const target = frameRef.current?.parentElement;
    if (!target?.requestFullscreen) {
      setDiagnostic({ code: "fullscreen_unavailable", status: 0 });
      setPhase("degraded");
      return;
    }
    try {
      await target.requestFullscreen();
    } catch {
      setDiagnostic({ code: "fullscreen_denied", status: 0 });
      setPhase("degraded");
    }
  }

  const loading = phase === "launching" || phase === "bootstrapping";
  const showRecovery = phase === "degraded" || phase === "error";

  return (
    <main className="design-studio-host" data-phase={phase}>
      <iframe
        key={launchRevision}
        ref={frameRef}
        name={frameNameRef.current}
        className="design-studio-frame"
        title="OpenDesign"
        referrerPolicy="no-referrer"
        allow="fullscreen"
        allowFullScreen
        onLoad={handleFrameLoad}
        onError={handleFrameError}
      />

      {loading ? (
        <div className="design-studio-state" role="status" aria-live="polite">
          <LoaderCircle className="spin" aria-hidden="true" />
          <strong>{phase === "launching" ? "Opening OpenDesign" : "Starting isolated session"}</strong>
          <span>The verified local runtime is preparing its workspace.</span>
        </div>
      ) : null}

      {showRecovery ? (
        <div className={`design-studio-state ${phase === "error" ? "is-error" : "is-degraded"}`} role="alert">
          <TriangleAlert aria-hidden="true" />
          <strong>{phase === "error" ? "OpenDesign is unavailable" : "OpenDesign is taking longer than expected"}</strong>
          <span>{diagnosticLabel(diagnostic)}</span>
          <button type="button" onClick={retry}>
            <RefreshCw size={17} aria-hidden="true" />
            Retry securely
          </button>
        </div>
      ) : null}

      {phase === "ready" ? (
        <div className="design-studio-toolbar" aria-label="OpenDesign host controls">
          <button type="button" onClick={retry} aria-label="Reload OpenDesign in a new isolated session" title="Reload isolated session">
            <RefreshCw size={17} aria-hidden="true" />
          </button>
          <button type="button" onClick={enterFullscreen} aria-label="Enter OpenDesign fullscreen" title="Fullscreen">
            <Expand size={18} aria-hidden="true" />
          </button>
        </div>
      ) : null}
    </main>
  );
}

function submitBootstrapForm(frame: HTMLIFrameElement, launch: SidecarLaunch) {
  const targetName = frame.name;
  if (!targetName) {
    throw new SidecarLaunchError("sidecar_frame_target_missing", 0);
  }
  const form = document.createElement("form");
  const ticket = document.createElement("input");
  form.method = "POST";
  form.action = launch.bootstrap_url;
  form.target = targetName;
  form.enctype = "application/x-www-form-urlencoded";
  form.hidden = true;
  ticket.type = "hidden";
  ticket.name = launch.ticket_field;
  ticket.value = launch.ticket;
  form.append(ticket);
  document.body.append(form);
  try {
    form.submit();
  } finally {
    ticket.value = "";
    form.remove();
  }
}

function diagnosticLabel(diagnostic: SidecarDiagnostic | null): string {
  if (!diagnostic) {
    return "The isolated session did not become ready.";
  }
  const status = diagnostic.status ? ` · HTTP ${diagnostic.status}` : "";
  return `Diagnostic: ${diagnostic.code}${status}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
