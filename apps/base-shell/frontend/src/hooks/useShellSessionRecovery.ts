import { useEffect, useRef } from "react";
import { shellAuthorizationEpoch } from "../shellAuthorization";
import { getSession, type SessionPayload } from "../api";

/** Foreground-only verification; connectivity hints never grant authorization. */
export function useShellSessionRecovery(onVerified: (session: SessionPayload) => Promise<void>): void {
  const verifiedRef = useRef(onVerified);
  verifiedRef.current = onVerified;
  useEffect(() => {
    let active = true;
    let controller: AbortController | null = null;
    const visible = () => !document.hidden && navigator.onLine !== false;
    const verify = () => {
      if (!active || controller || !visible()) return;
      const epoch = shellAuthorizationEpoch();
      const request = new AbortController();
      controller = request;
      void getSession(request.signal).then(async (session) => {
        if (active && !request.signal.aborted && epoch === shellAuthorizationEpoch()) await verifiedRef.current(session);
      }).catch(() => undefined).finally(() => {
        if (controller === request) controller = null;
      });
    };
    const onVisibility = () => {
      if (visible()) verify();
      else { controller?.abort(); controller = null; }
    };
    const timer = window.setInterval(verify, 5 * 60_000);
    const events = ["online", "focus", "pageshow", "maverick.session-changed"];
    for (const event of events) window.addEventListener(event, verify);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      active = false;
      controller?.abort();
      window.clearInterval(timer);
      for (const event of events) window.removeEventListener(event, verify);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);
}
