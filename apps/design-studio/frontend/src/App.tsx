import { useCallback, useEffect, useRef, useState } from "react";
import { Expand, LoaderCircle, Plus, RefreshCw, TriangleAlert } from "lucide-react";
import {
  currentDesignStudioAppId,
  initialNavigation,
  isTrustedSidecarMessage,
  navigationFromParams,
  navigationMessage,
  openSettingsMessage,
  readCachedLaunchTarget,
  requestOpenDesignLaunch,
  SidecarLaunchError,
  themeMessage,
  writeCachedLaunchTarget,
} from "./api";
import { BackendRequestError, callDesignStudioBackend } from "./backendApi";
import { startNonOverlappingPoll } from "./startupStatusPolling";
import type { OpenDesignLaunchTarget, OpenDesignNavigation, SidecarDiagnostic, SidecarHostPhase, SidecarLaunch } from "./types";
import "./styles/main.css";

const LOADING_STATE_DELAY_MS = 500;
const STARTUP_STATUS_POLL_DELAY_MS = 1_000;
const STARTUP_STATUS_POLL_MS = 400;
const MAX_RETRY_BACKOFF_MS = 8_000;

export function App() {
  const appId = currentDesignStudioAppId();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const frameNameRef = useRef(`opendesign-${crypto.randomUUID()}`);
  const submittedFrameRef = useRef<HTMLIFrameElement | null>(null);
  const sidecarOriginRef = useRef("");
  const sidecarInstanceRef = useRef("");
  const launchStartedRef = useRef(0);
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef(0);
  const startupFailureRef = useRef<SidecarDiagnostic | null>(null);
  const transactionalReadyRef = useRef(false);
  const stopStartupStatusPollRef = useRef<() => void>(() => undefined);
  const navigationRef = useRef<OpenDesignNavigation>(initialNavigation());
  const settingsRequestRef = useRef(initialSettingsRequest());
  const deliveredSettingsRequestRef = useRef("");
  const settingsDeliveryAttemptsRef = useRef(0);
  const themeRef = useRef<"dark" | "light">(initialTheme());
  const [, setNavigation] = useState(navigationRef.current);
  const [phase, setPhase] = useState<SidecarHostPhase>("launching");
  const [diagnostic, setDiagnostic] = useState<SidecarDiagnostic | null>(null);
  const [launchRevision, setLaunchRevision] = useState(0);
  const [frameRevision, setFrameRevision] = useState(0);
  const [loadingVisible, setLoadingVisible] = useState(false);
  const [startupLabel, setStartupLabel] = useState("Avvio runtime verificato");
  const [retryPending, setRetryPending] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const postNavigation = useCallback(() => {
    const frameWindow = frameRef.current?.contentWindow;
    const origin = sidecarOriginRef.current;
    if (!frameWindow || !origin) {
      return;
    }
    frameWindow.postMessage(navigationMessage(navigationRef.current), origin);
  }, []);

  const postTheme = useCallback(() => {
    const frameWindow = frameRef.current?.contentWindow;
    const origin = sidecarOriginRef.current;
    if (frameWindow && origin) {
      frameWindow.postMessage(themeMessage(themeRef.current), origin);
    }
  }, []);

  const postSettings = useCallback(() => {
    const requestId = settingsRequestRef.current;
    if (!requestId || deliveredSettingsRequestRef.current === requestId) {
      return;
    }
    function send() {
      const frameWindow = frameRef.current?.contentWindow;
      const origin = sidecarOriginRef.current;
      if (
        !frameWindow
        || !origin
        || deliveredSettingsRequestRef.current === requestId
        || settingsDeliveryAttemptsRef.current >= 40
      ) {
        return;
      }
      settingsDeliveryAttemptsRef.current += 1;
      frameWindow.postMessage(openSettingsMessage(), origin);
      window.setTimeout(send, 250);
    }
    send();
  }, []);

  const openInShell = useCallback((projectId: string, extra: Record<string, string> = {}) => {
    window.parent?.postMessage(
      {
        type: "maverick.app.open-app",
        app_id: appId,
        params: { ...(projectId ? { od_project_id: projectId } : {}), ...extra },
      },
      window.location.origin,
    );
  }, [appId]);

  useEffect(() => {
    window.parent?.postMessage({ type: "maverick.app.ready", app_id: appId }, window.location.origin);
  }, [appId]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin === window.location.origin && event.source === window.parent && isRecord(event.data)) {
        if (event.data.type === "maverick.shell.theme-changed") {
          const shellTheme = isRecord(event.data.theme) ? event.data.theme.effective : "";
          if (shellTheme === "dark" || shellTheme === "light") {
            themeRef.current = shellTheme;
            document.documentElement.dataset.theme = shellTheme;
            postTheme();
          }
          return;
        }
        if (event.data.type !== "maverick.app.navigate") {
          return;
        }
        if (event.data.app_id && event.data.app_id !== appId) {
          return;
        }
        const params = isRecord(event.data.params)
          ? event.data.params as Record<string, string | boolean | null>
          : {};
        const settingsRequest = scalarString(params.open_settings_request_id);
        if (settingsRequest && settingsRequest !== settingsRequestRef.current) {
          settingsRequestRef.current = settingsRequest;
          deliveredSettingsRequestRef.current = "";
          settingsDeliveryAttemptsRef.current = 0;
          postSettings();
        }
        const next = settingsRequest && !scalarString(params.od_project_id)
          ? navigationRef.current
          : navigationFromParams(params);
        if (next.od_project_id === navigationRef.current.od_project_id && next.od_run_id === navigationRef.current.od_run_id) {
          return;
        }
        setEmpty(!next.od_project_id);
        navigationRef.current = next;
        setNavigation(next);
        postNavigation();
        return;
      }
      const frameWindow = frameRef.current?.contentWindow || null;
      if (!isTrustedSidecarMessage(event, sidecarOriginRef.current, frameWindow) || !isRecord(event.data)) {
        return;
      }
      if (event.data.type === "maverick.opendesign.ready" && event.data.version === 1) {
        if (transactionalReadyRef.current) {
          return;
        }
        stopStartupStatusPollRef.current();
        stopStartupStatusPollRef.current = () => undefined;
        if (startupFailureRef.current) {
          setDiagnostic(startupFailureRef.current);
          setPhase("error");
          setLoadingVisible(false);
          return;
        }
        transactionalReadyRef.current = true;
        setDiagnostic(null);
        setPhase("ready");
        setLoadingVisible(false);
        retryCountRef.current = 0;
        recordFirstPaint(launchStartedRef.current, "maverick.opendesign.ready", appId);
        launchStartedRef.current = 0;
        postNavigation();
        postTheme();
        postSettings();
        return;
      }
      if (event.data.type === "maverick.opendesign.navigation-changed" && event.data.version === 1) {
        const next = navigationFromParams({ od_project_id: typeof event.data.od_project_id === "string" ? event.data.od_project_id : "" });
        if (!next.od_project_id || next.od_project_id === navigationRef.current.od_project_id) {
          return;
        }
        navigationRef.current = next;
        setNavigation(next);
        setEmpty(false);
        openInShell(next.od_project_id);
        return;
      }
      if (event.data.type === "maverick.opendesign.settings-opened" && event.data.version === 1) {
        deliveredSettingsRequestRef.current = settingsRequestRef.current;
        setSettingsOpen(true);
        return;
      }
      if (event.data.type === "maverick.opendesign.settings-closed" && event.data.version === 1) {
        setSettingsOpen(false);
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [appId, openInShell, postNavigation, postSettings, postTheme]);

  useEffect(() => {
    let canceled = false;
    const abortController = new AbortController();
    let loadingTimer = 0;
    let statusPollTimer = 0;
    let stopStatusPoll: () => void = () => undefined;
    stopStartupStatusPollRef.current();
    stopStartupStatusPollRef.current = () => undefined;
    submittedFrameRef.current = null;
    startupFailureRef.current = null;
    transactionalReadyRef.current = false;
    sidecarOriginRef.current = "";
    deliveredSettingsRequestRef.current = "";
    settingsDeliveryAttemptsRef.current = 0;
    setDiagnostic(null);
    setPhase("launching");
    setLoadingVisible(false);
    setStartupLabel("Avvio runtime verificato");
    launchStartedRef.current = performance.now();
    loadingTimer = window.setTimeout(() => {
      if (canceled || transactionalReadyRef.current) {
        return;
      }
      setLoadingVisible(true);
    }, LOADING_STATE_DELAY_MS);
    statusPollTimer = window.setTimeout(() => {
      if (canceled || transactionalReadyRef.current) {
        return;
      }
      stopStatusPoll = startNonOverlappingPoll({
        intervalMs: STARTUP_STATUS_POLL_MS,
        poll: () => pollStartupStatus(appId, abortController.signal),
        onResult: (status) => {
          if (canceled || !status) {
            return;
          }
          setStartupLabel(startupPhaseLabel(status.phase, status.health?.repair_state));
          if (status.health?.repair_state === "repairing" || status.phase === "repair") {
            setPhase("repairing");
          }
        },
      });
      stopStartupStatusPollRef.current = stopStatusPoll;
    }, STARTUP_STATUS_POLL_DELAY_MS);

    const requestedNavigation = navigationRef.current;
    let failureReported = false;

    function applyTarget(target: OpenDesignLaunchTarget, { authoritative }: { authoritative: boolean }) {
      if (canceled) {
        return;
      }
      const resolved = navigationFromParams({ od_project_id: target.od_project_id });
      const shouldSyncShell = Boolean(
        authoritative
        && resolved.od_project_id
        && resolved.od_project_id !== requestedNavigation.od_project_id,
      );
      navigationRef.current = resolved;
      setNavigation(resolved);
      setEmpty(target.target === "empty");
      postNavigation();
      if (shouldSyncShell) {
        openInShell(resolved.od_project_id);
      }
    }

    function reportStartupError(error: unknown, fallbackCode: string, fallbackPhase: string) {
      if (canceled || failureReported || (error instanceof DOMException && error.name === "AbortError")) {
        return;
      }
      failureReported = true;
      const launchError = error instanceof SidecarLaunchError
        ? error
        : error instanceof BackendRequestError
          ? new SidecarLaunchError(
              error.code,
              error.status,
              error.phase,
              error.autoRepairable,
              error.retryable,
            )
          : new SidecarLaunchError(fallbackCode, 0, fallbackPhase);
      const nextDiagnostic = {
        code: launchError.code,
        status: launchError.status,
        phase: launchError.phase,
        autoRepairable: launchError.autoRepairable,
        retryable: launchError.retryable,
      };
      startupFailureRef.current = nextDiagnostic;
      stopStartupStatusPollRef.current();
      stopStartupStatusPollRef.current = () => undefined;
      setDiagnostic(nextDiagnostic);
      setPhase("error");
      setLoadingVisible(false);
    }

    void requestOpenDesignLaunch(
      appId,
      requestedNavigation,
      window.location.origin,
      abortController.signal,
    )
      .then(async (launch) => {
        if (canceled) {
          return;
        }
        const requestedTarget: OpenDesignLaunchTarget | null = requestedNavigation.od_project_id
          ? {
              target: "project",
              od_project_id: requestedNavigation.od_project_id,
              project: { id: requestedNavigation.od_project_id },
            }
          : null;
        const cachedTarget = requestedTarget
          || readCachedLaunchTarget(sessionStorage, appId, launch.origin);
        if (cachedTarget) {
          applyTarget(cachedTarget, { authoritative: false });
          writeCachedLaunchTarget(sessionStorage, appId, launch.origin, cachedTarget);
        }
        const instanceChanged = Boolean(
          sidecarInstanceRef.current
          && sidecarInstanceRef.current !== launch.sidecar_instance_id,
        );
        sidecarInstanceRef.current = launch.sidecar_instance_id;
        if (instanceChanged) {
          setFrameRevision((value) => value + 1);
          await nextAnimationFrame();
        }
        const frame = frameRef.current;
        if (canceled || !frame) {
          return;
        }
        sidecarOriginRef.current = launch.origin;
        setPhase("bootstrapping");
        setStartupLabel("Attivazione transazionale dell’interfaccia");
        submittedFrameRef.current = frame;
        submitBootstrapForm(frame, launch);
        if (!cachedTarget) {
          void callDesignStudioBackend<OpenDesignLaunchTarget>(
            "resolve_launch_target",
            {},
            appId,
            { signal: abortController.signal },
          )
            .then((target) => {
              applyTarget(target, { authoritative: true });
              writeCachedLaunchTarget(sessionStorage, appId, launch.origin, target);
            })
            .catch((error: unknown) => reportStartupError(error, "launch_target_failed", "launch_target_resolution"));
        }
      })
      .catch((error: unknown) => reportStartupError(error, "browser_ticket_failed", "browser_ticket_issue"));

    return () => {
      canceled = true;
      abortController.abort();
      window.clearTimeout(loadingTimer);
      window.clearTimeout(statusPollTimer);
      stopStatusPoll();
      stopStartupStatusPollRef.current = () => undefined;
    };
  }, [appId, launchRevision, openInShell]);

  useEffect(() => () => window.clearTimeout(retryTimerRef.current), []);

  function handleFrameError() {
    if (submittedFrameRef.current !== frameRef.current) {
      return;
    }
    setDiagnostic({
      code: "sidecar_frame_load_failed",
      status: 0,
      phase: "browser",
      autoRepairable: false,
      retryable: true,
    });
    setPhase("error");
  }

  function retry() {
    if (retryPending || diagnostic?.retryable === false) {
      return;
    }
    const delay = Math.min(500 * (2 ** retryCountRef.current), MAX_RETRY_BACKOFF_MS);
    retryCountRef.current += 1;
    setRetryPending(true);
    retryTimerRef.current = window.setTimeout(() => {
      setRetryPending(false);
      setLaunchRevision((value) => value + 1);
    }, delay);
  }

  async function createProject() {
    if (creating) {
      return;
    }
    setCreating(true);
    setCreateError("");
    try {
      const payload = await callDesignStudioBackend<{ od_project_id?: string; project?: { id?: string } }>(
        "create_project",
        { name: "Untitled design" },
        appId,
      );
      const projectId = payload.od_project_id || payload.project?.id || "";
      if (!projectId) {
        throw new Error("OpenDesign did not return the new project.");
      }
      const next = navigationFromParams({ od_project_id: projectId });
      navigationRef.current = next;
      setNavigation(next);
      setEmpty(false);
      if (sidecarOriginRef.current) {
        writeCachedLaunchTarget(sessionStorage, appId, sidecarOriginRef.current, {
          target: "project",
          od_project_id: projectId,
          project: payload.project || { id: projectId },
        });
      }
      postNavigation();
      openInShell(projectId);
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : "Unable to create the project.");
    } finally {
      setCreating(false);
    }
  }

  async function enterFullscreen() {
    const target = frameRef.current?.parentElement;
    if (!target?.requestFullscreen) {
      setDiagnostic({ code: "fullscreen_unavailable", status: 0, retryable: false });
      setPhase("degraded");
      return;
    }
    try {
      await target.requestFullscreen();
    } catch {
      setDiagnostic({ code: "fullscreen_denied", status: 0, retryable: false });
      setPhase("degraded");
    }
  }

  const loading = loadingVisible && (phase === "launching" || phase === "bootstrapping" || phase === "repairing");
  const showRecovery = phase === "degraded" || phase === "error";
  const retryAllowed = diagnostic?.retryable !== false;

  return (
    <main className={`design-studio-host ${empty ? "is-empty" : ""} ${settingsOpen ? "is-settings-open" : ""}`} data-phase={phase}>
      <iframe
        key={frameRevision}
        ref={frameRef}
        name={frameNameRef.current}
        className="design-studio-frame"
        title="OpenDesign"
        referrerPolicy="no-referrer"
        allow="fullscreen"
        allowFullScreen
        onError={handleFrameError}
      />

      {loading ? (
        <div className="design-studio-state" role="status" aria-live="polite">
          <LoaderCircle className="spin" aria-hidden="true" />
          <strong>{phase === "repairing" ? "Ripristino sicuro del runtime" : startupLabel}</strong>
          <span>{phase === "repairing" ? "La nuova generazione sarà pubblicata atomicamente." : "Preparazione dello spazio di lavoro isolato."}</span>
        </div>
      ) : null}

      {showRecovery ? (
        <div className={`design-studio-state ${phase === "error" ? "is-error" : "is-degraded"}`} role="alert">
          <TriangleAlert aria-hidden="true" />
          <strong>{phase === "error" ? "OpenDesign is unavailable" : "OpenDesign is taking longer than expected"}</strong>
          <span>{diagnosticLabel(diagnostic)}</span>
          {retryAllowed ? (
            <button data-testid="opendesign-retry" type="button" disabled={retryPending} onClick={retry}>
              <RefreshCw size={17} aria-hidden="true" />
              {retryPending ? "Attesa prima del nuovo tentativo" : "Riprova in sicurezza"}
            </button>
          ) : null}
        </div>
      ) : null}

      {phase === "ready" && empty && !settingsOpen ? (
        <div className="design-studio-empty">
          <button disabled={creating} onClick={() => void createProject()} type="button">
            {creating ? <LoaderCircle aria-hidden="true" className="spin" /> : <Plus aria-hidden="true" />}
            <span>Nuovo progetto</span>
          </button>
          {createError ? <p role="alert">{createError}</p> : null}
        </div>
      ) : null}

      {phase === "ready" && !empty ? (
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

function initialTheme(): "dark" | "light" {
  const value = new URLSearchParams(window.location.search).get("maverick_theme");
  return value === "light" ? "light" : "dark";
}

function initialSettingsRequest(search = window.location.search): string {
  return scalarString(new URLSearchParams(search).get("open_settings_request_id"));
}

function scalarString(value: unknown): string {
  return typeof value === "string" && value.length <= 128 ? value.trim() : "";
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
  const labels: Record<string, string> = {
    artifact_missing: "Il runtime verificato non è disponibile.",
    artifact_integrity_mismatch: "L’integrità del runtime non corrisponde all’attestazione.",
    artifact_permissions_invalid: "Le protezioni dello store runtime non sono valide.",
    artifact_repairing: "È in corso un ripristino sicuro del runtime.",
    artifact_repair_failed: "Il ripristino del runtime non ha superato la verifica.",
    runtime_binding_invalid: "Runtime, interfaccia e dati non sono compatibili.",
    daemon_spawn_failed: "Il processo OpenDesign non si è avviato.",
    daemon_ready_timeout: "OpenDesign non ha raggiunto la readiness transazionale.",
    activation_incomplete: "L’attivazione dell’interfaccia non è stata completata.",
    browser_ticket_failed: "Non è stato possibile emettere il ticket browser one-shot.",
  };
  const status = diagnostic.status ? ` HTTP ${diagnostic.status}.` : "";
  return `${labels[diagnostic.code] || `Diagnostica: ${diagnostic.code}.`}${status}`;
}

type StartupRuntimeStatus = {
  phase?: string;
  health?: { repair_state?: string };
};

async function pollStartupStatus(appId: string, signal: AbortSignal): Promise<StartupRuntimeStatus | null> {
  try {
    const payload = await callDesignStudioBackend<{
      opendesign?: { runtime?: StartupRuntimeStatus };
    }>("state", {}, appId, { signal });
    return payload.opendesign?.runtime || null;
  } catch {
    return null;
  }
}

function startupPhaseLabel(phase = "", repairState = ""): string {
  if (repairState === "repairing" || phase.includes("repair")) {
    return "Ripristino sicuro del runtime";
  }
  const labels: Record<string, string> = {
    bootstrap: "Preparazione dell’avvio verificato",
    artifact_verified: "Avvio runtime verificato",
    daemon_starting: "Avvio del daemon OpenDesign",
    activation_commit: "Attivazione transazionale dell’interfaccia",
    browser_ready: "Preparazione del ticket browser",
  };
  return labels[phase] || "Avvio runtime verificato";
}

function nextAnimationFrame(): Promise<void> {
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

function recordFirstPaint(startedAt: number, source: string, appId: string): void {
  if (!(startedAt > 0)) {
    return;
  }
  const durationMs = Math.max(0, performance.now() - startedAt);
  performance.mark("maverick.opendesign.first-paint");
  const event = {
    type: "maverick.app.telemetry",
    app_id: appId,
    metric: "first_paint_ms",
    value_ms: Math.round(durationMs * 1000) / 1000,
    source,
  };
  console.info("maverick.opendesign.first-paint", event);
  window.parent?.postMessage(event, window.location.origin);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
