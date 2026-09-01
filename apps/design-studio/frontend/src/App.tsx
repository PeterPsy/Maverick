import { useEffect, useRef, useState } from "react";

import {
  currentDesignStudioAppId,
  nativeOpenDesignPath,
  requestOpenDesignBootstrapStatus,
  requestOpenDesignLaunch,
  SidecarLaunchError,
} from "./api";
import type { SidecarHostPhase, SidecarLaunch } from "./types";
import "./styles/main.css";

const LOADING_DELAY_MS = 300;
const BOOTSTRAP_STATUS_POLL_MS = 200;

function maverickPlatformOrigin(): string {
  const value = (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: unknown }).__MAVERICK_PLATFORM_ORIGIN__;
  return typeof value === "string" && /^https?:\/\//u.test(value) ? value : window.location.origin;
}

export function App() {
  const appId = currentDesignStudioAppId();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const submittedFrameRef = useRef<HTMLIFrameElement | null>(null);
  const bootstrapLoadArmedRef = useRef(false);
  const bootstrapLoadedRef = useRef(false);
  const bootstrapConfirmedRef = useRef(false);
  const bootstrapArmTimerRef = useRef<number | null>(null);
  const bootstrapPollTimerRef = useRef<number | null>(null);
  const [frameName, setFrameName] = useState(() => `opendesign-${crypto.randomUUID()}`);
  const [nativePath, setNativePath] = useState(() => nativeOpenDesignPath(window.location.search));
  const [launchRevision, setLaunchRevision] = useState(0);
  const [phase, setPhase] = useState<SidecarHostPhase>("launching");
  const [loadingVisible, setLoadingVisible] = useState(false);
  const [errorCode, setErrorCode] = useState("");

  useEffect(() => {
    window.parent?.postMessage({ type: "maverick.app.ready", app_id: appId }, "*");
  }, [appId]);

  useEffect(() => {
    function handleShellNavigation(event: MessageEvent) {
      if (event.origin !== window.location.origin || event.source !== window || !isRecord(event.data)) {
        return;
      }
      if (event.data.type !== "maverick.app.navigate" || (event.data.app_id && event.data.app_id !== appId)) {
        return;
      }
      const params = isRecord(event.data.params) ? event.data.params : {};
      const nextPath = nativeOpenDesignPath(params);
      if (nextPath === nativePath) {
        return;
      }
      setNativePath(nextPath);
      setFrameName(`opendesign-${crypto.randomUUID()}`);
      setLaunchRevision((value) => value + 1);
    }
    window.addEventListener("message", handleShellNavigation);
    return () => window.removeEventListener("message", handleShellNavigation);
  }, [appId, nativePath]);

  useEffect(() => {
    const abort = new AbortController();
    submittedFrameRef.current = null;
    bootstrapLoadArmedRef.current = false;
    bootstrapLoadedRef.current = false;
    bootstrapConfirmedRef.current = false;
    if (bootstrapArmTimerRef.current !== null) window.clearTimeout(bootstrapArmTimerRef.current);
    if (bootstrapPollTimerRef.current !== null) window.clearTimeout(bootstrapPollTimerRef.current);
    setPhase("launching");
    setLoadingVisible(false);
    setErrorCode("");
    const loadingTimer = window.setTimeout(() => setLoadingVisible(true), LOADING_DELAY_MS);

    void requestOpenDesignLaunch(appId, nativePath, maverickPlatformOrigin(), abort.signal)
      .then((launch) => {
        if (abort.signal.aborted) return;
        const frame = frameRef.current;
        if (!frame) throw new SidecarLaunchError("sidecar_frame_target_missing", 0);
        submittedFrameRef.current = frame;
        setPhase("bootstrapping");
        submitBootstrapForm(frame, launch);
        // Ignore the iframe's initial same-origin about:blank load.  The
        // one-shot POST navigation cannot complete in the same task.
        bootstrapArmTimerRef.current = window.setTimeout(() => {
          bootstrapLoadArmedRef.current = true;
          bootstrapArmTimerRef.current = null;
        }, 0);

        const confirmationDeadline = Date.now() + launch.expires_in_seconds * 1000;
        const pollConfirmation = () => {
          void requestOpenDesignBootstrapStatus(appId, launch, abort.signal)
            .then((status) => {
              if (abort.signal.aborted) return;
              if (status === "ready") {
                bootstrapConfirmedRef.current = true;
                if (bootstrapLoadedRef.current) {
                  setPhase("ready");
                  setLoadingVisible(false);
                }
                return;
              }
              if (Date.now() >= confirmationDeadline) {
                throw new SidecarLaunchError("sidecar_bootstrap_unconfirmed", 408);
              }
              bootstrapPollTimerRef.current = window.setTimeout(
                pollConfirmation,
                BOOTSTRAP_STATUS_POLL_MS,
              );
            })
            .catch((error: unknown) => {
              if (abort.signal.aborted) return;
              setErrorCode(
                error instanceof SidecarLaunchError
                  ? error.code
                  : "sidecar_bootstrap_confirmation_failed",
              );
              setPhase("error");
              setLoadingVisible(false);
            });
        };
        pollConfirmation();
      })
      .catch((error: unknown) => {
        if (abort.signal.aborted) return;
        setErrorCode(error instanceof SidecarLaunchError ? error.code : "browser_ticket_failed");
        setPhase("error");
        setLoadingVisible(false);
      });

    return () => {
      abort.abort();
      window.clearTimeout(loadingTimer);
      if (bootstrapArmTimerRef.current !== null) window.clearTimeout(bootstrapArmTimerRef.current);
      bootstrapArmTimerRef.current = null;
      bootstrapLoadArmedRef.current = false;
      if (bootstrapPollTimerRef.current !== null) window.clearTimeout(bootstrapPollTimerRef.current);
      bootstrapPollTimerRef.current = null;
      bootstrapLoadedRef.current = false;
      bootstrapConfirmedRef.current = false;
    };
  }, [appId, launchRevision, nativePath]);

  function markNativeLoaded() {
    if (!bootstrapLoadArmedRef.current || submittedFrameRef.current !== frameRef.current) return;
    bootstrapLoadedRef.current = true;
    if (bootstrapConfirmedRef.current) {
      setPhase("ready");
      setLoadingVisible(false);
    }
  }

  function markNativeLoadFailed() {
    if (submittedFrameRef.current !== frameRef.current) return;
    setErrorCode("sidecar_frame_load_failed");
    setPhase("error");
    setLoadingVisible(false);
  }

  function retry() {
    setFrameName(`opendesign-${crypto.randomUUID()}`);
    setLaunchRevision((value) => value + 1);
  }

  const loading = loadingVisible && phase !== "ready" && phase !== "error";
  return (
    <main className="design-studio-host" data-phase={phase}>
      <iframe
        key={frameName}
        ref={frameRef}
        name={frameName}
        className="design-studio-frame"
        title="OpenDesign"
        referrerPolicy="no-referrer"
        allow="clipboard-read; clipboard-write; fullscreen"
        allowFullScreen
        onLoad={markNativeLoaded}
        onError={markNativeLoadFailed}
      />

      {loading ? (
        <div className="design-studio-state" role="status" aria-live="polite">
          <span className="design-studio-spinner" aria-hidden="true" />
          <strong>Avvio di OpenDesign</strong>
          <span>Preparazione dell’applicazione nativa nello spazio di lavoro isolato.</span>
        </div>
      ) : null}

      {phase === "error" ? (
        <div className="design-studio-state is-error" role="alert">
          <strong>OpenDesign non è disponibile</strong>
          <span>{diagnosticLabel(errorCode)}</span>
          <button data-testid="opendesign-retry" type="button" onClick={retry}>Riprova</button>
        </div>
      ) : null}
    </main>
  );
}

function submitBootstrapForm(frame: HTMLIFrameElement, launch: SidecarLaunch) {
  if (!frame.name) throw new SidecarLaunchError("sidecar_frame_target_missing", 0);
  const form = document.createElement("form");
  const ticket = document.createElement("input");
  form.method = "POST";
  form.action = launch.bootstrap_url;
  form.target = frame.name;
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

function diagnosticLabel(code: string): string {
  const labels: Record<string, string> = {
    artifact_missing: "Il pacchetto ufficiale verificato non è installato.",
    artifact_integrity_mismatch: "Il pacchetto ufficiale non supera la verifica di integrità.",
    browser_ticket_failed: "Non è stato possibile autorizzare l’origine isolata.",
    daemon_ready_timeout: "OpenDesign non ha raggiunto lo stato pronto.",
    sidecar_bootstrap_confirmation_expired: "Core non ha confermato l’avvio dell’origine isolata.",
    sidecar_bootstrap_confirmation_failed: "La verifica dell’avvio isolato non è riuscita.",
    sidecar_bootstrap_confirmation_invalid: "Core ha restituito una conferma di avvio non valida.",
    sidecar_bootstrap_unconfirmed: "L’origine isolata non ha completato l’avvio entro il tempo previsto.",
    sidecar_frame_load_failed: "L’applicazione nativa non è stata caricata.",
  };
  return labels[code] || `Diagnostica: ${code || "errore_sconosciuto"}.`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
