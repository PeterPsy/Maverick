import { useState, useEffect, useCallback, useRef, type FormEvent } from "react";
import { operation, type Session, type Row } from "./api";
import { Icon } from "./Icons";
import { Dialog } from "./Dialog";
import { useVisiblePolling } from "./useVisiblePolling";

export function SessionPanel({
  session,
  canManage,
  onRefresh,
  onClose,
}: {
  session: Session;
  canManage: boolean;
  onRefresh: () => void;
  onClose: () => void;
}) {
  const [qr, setQr] = useState("");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [qrError, setQrError] = useState("");
  const acting = useRef(false);
  const linking = canManage && ["qr_ready", "authenticating", "initializing"].includes(session.status);
  useEffect(() => {
    if (!linking) { setQr(""); setQrError(""); }
    if (session.status === "ready" || !session.engineLoaded) setCode("");
  }, [linking, session.status, session.engineLoaded]);
  const loadQr = useCallback(async (signal: AbortSignal) => {
    try {
      const data = await operation<Row>("session.qr", { session_id: session.id }, signal);
      if (signal.aborted) return;
      const image = data.qrCode || data.qr || data.dataUrl;
      setQr(typeof image === "string" && image.startsWith("data:image/png;base64,") ? image : "");
      setQrError("");
    } catch (error) {
      if (!signal.aborted) { setQr(""); setQrError((error as Error).message); return false; }
    }
  }, [session.id]);
  const refreshQr = useVisiblePolling(loadQr, 5000, linking);
  async function act(action: string, extra: Row = {}) {
    if (acting.current || !canManage) return;
    acting.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await operation<Row>(action, {
        session_id: session.id,
        ...extra,
      });
      if (action === "session.pair")
        setCode(String(result.code || result.pairingCode || ""));
      onRefresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      acting.current = false;
      setBusy(false);
    }
  }
  return (
    <Dialog label="Manage WhatsApp session" onClose={onClose}>
      <section className="modal">
        <div className="panel-heading">
          <h2>{session.name}</h2>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Close session"
          >
            <Icon name="close" />
          </button>
        </div>
        <p className="muted">
          {session.phone || "Link this device from WhatsApp on your phone."}
        </p>
        {session.status !== "ready" && <span className={"status-pill " + session.status}>
          {session.status.replaceAll("_", " ")}
        </span>}
        {session.lastError && (
          <p className="error-banner">{session.lastError}</p>
        )}
        {qr && (
          <div className="qr-card">
            <img src={qr} alt="WhatsApp linking QR code" />
            <p>WhatsApp → Settings → Linked devices → Link a device</p>
          </div>
        )}
        {linking && !qr && !qrError && <p className="notice" role="status">Waiting for a linking QR code…</p>}
        {qrError && <div className="error-banner" role="alert">{qrError}<button onClick={refreshQr}>Retry QR</button></div>}
        {canManage && session.engineLoaded && session.status !== "ready" && (
          <form
            className="pair-form"
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              act("session.pair", { phone });
            }}
          >
            <label>
              Or link with your phone number
              <input
                inputMode="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="Country code + number"
                pattern="[1-9][0-9]{7,14}"
                required
              />
            </label>
            <button disabled={busy}>Get linking code</button>
            {code && <output className="pair-code">{code}</output>}
          </form>
        )}
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        <div className="button-row">
          <button
            className="primary"
            onClick={() => act("session.start")}
            disabled={busy || !canManage || session.engineLoaded}
          >
            Start session
          </button>
          <button
            onClick={() => act("session.stop")}
            disabled={busy || !canManage || !session.engineLoaded}
          >
            Stop
          </button>
        </div>
        <details>
          <summary>Unlink device</summary>
          <p className="small muted">
            Logging out removes this linked WhatsApp device. You will need to
            link it again.
          </p>
          <button
            className="danger"
            disabled={busy || !canManage}
            onClick={() => {
              if (window.confirm("Unlink this device from WhatsApp?"))
                act("session.logout");
            }}
          >
            Log out of WhatsApp
          </button>
        </details>
      </section>
    </Dialog>
  );
}
