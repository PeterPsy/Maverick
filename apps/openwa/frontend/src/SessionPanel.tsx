import { useState, useEffect, type FormEvent } from "react";
import { operation, type Session, type Row } from "./api";
import { Icon } from "./Icons";
import { Dialog } from "./Dialog";
import { maverickAppIsVisible, observeMaverickVisibility } from "@maverick/pwa-cache";

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
  useEffect(() => {
    setQr("");
    setCode("");
    let active = true;
    const load = () =>
      operation<Row>("session.qr", { session_id: session.id })
        .then((data) => {
          const image = data.qrCode || data.qr || data.dataUrl;
          if (
            active &&
            typeof image === "string" &&
            image.startsWith("data:image/png;base64,")
          )
            setQr(image);
        })
        .catch(() => {});
    if (canManage && (
      session.status === "qr_ready" ||
      session.status === "authenticating" ||
      session.status === "initializing"
    )) {
      const stop = observeMaverickVisibility((visible) => { if (visible) load(); });
      const timer = setInterval(() => { if (maverickAppIsVisible()) load(); }, 5000);
      return () => {
        active = false;
        stop();
        clearInterval(timer);
      };
    }
    return () => {
      active = false;
    };
  }, [session.id, session.status, canManage]);
  async function act(action: string, extra: Row = {}) {
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
        <span className={"status-pill " + session.status}>
          {session.status.replaceAll("_", " ")}
        </span>
        {session.lastError && (
          <p className="error-banner">{session.lastError}</p>
        )}
        {qr && (
          <div className="qr-card">
            <img src={qr} alt="WhatsApp linking QR code" />
            <p>WhatsApp → Settings → Linked devices → Link a device</p>
          </div>
        )}
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
