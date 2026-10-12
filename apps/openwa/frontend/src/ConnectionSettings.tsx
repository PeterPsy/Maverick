import { useRef, useState, type FormEvent } from "react";
import { callBackend, type Status } from "./api";
import { Icon } from "./Icons";

export function ConnectionSettings({
  status,
  onSaved,
  onClose,
}: {
  status: Status;
  onSaved: () => void;
  onClose?: () => void;
}) {
  const [url, setUrl] = useState(status.connection.url);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const saving = useRef(false);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving.current || !status.can_configure || !status.connection.credential_available) return;
    saving.current = true;
    setError("");
    setBusy(true);
    try {
      await callBackend({
        action: "connection.save",
        url,
      });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="setup-card">
      <div className="setup-top">
        <span className="brand-icon">
          <Icon name="whatsapp" size={30} />
        </span>
        {onClose && (
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Close settings"
          >
            <Icon name="close" />
          </button>
        )}
      </div>
      <p className="eyebrow">YOUR WHATSAPP WORKSPACE</p>
      <h1>
        {status.connection.configured
          ? "Gateway settings"
          : "Connect your conversations"}
      </h1>
      <p className="muted">
        Bring your WhatsApp sessions, conversations and messages into Maverick
        with OpenWA.
      </p>
      {status.can_configure ? (
        <form onSubmit={save}>
          <label>
            Gateway URL
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://openwa.example.com"
              required
              autoComplete="url"
            />
          </label>
          <p className="small muted">
            {status.connection.credential_available
              ? "The API key is available in Maverick Vault and used only by the server."
              : "Add an OpenWA API key and grant this app access in Maverick Vault before connecting."}
            {" "}When changing gateways, update its key and app access in Vault first.
          </p>
          {error && (
            <div className="error-banner" role="alert">
              {error}
            </div>
          )}
          <button className="primary wide" disabled={busy || !status.connection.credential_available}>
            {busy ? "Connecting…" : "Connect gateway"}
            <Icon name="link" size={18} />
          </button>
        </form>
      ) : (
        <p className="notice">
          Ask your workspace administrator to connect OpenWA.
        </p>
      )}
      <div className="setup-footer">
        <span className="dot" /> Self hosted · Open source · MIT license
      </div>
    </section>
  );
}
