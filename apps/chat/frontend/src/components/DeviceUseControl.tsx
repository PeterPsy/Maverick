import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type {
  DeviceUseConsentMode,
  DeviceUseMode,
  DeviceUsePermission,
  NativeDeviceUseSnapshot,
} from "../lib/deviceUse";

export function DeviceUseControl({
  busy,
  locked,
  mode,
  onConfigure,
  onModeChange,
  onRefresh,
  onRequestPermission,
  snapshot,
}: {
  busy: boolean;
  locked: boolean;
  mode: DeviceUseMode;
  onConfigure: (settings: NativeDeviceUseSnapshot["settings"]) => Promise<void>;
  onModeChange: (mode: DeviceUseMode) => void;
  onRefresh: () => Promise<NativeDeviceUseSnapshot>;
  onRequestPermission: (permission: DeviceUsePermission) => void;
  snapshot: NativeDeviceUseSnapshot;
}) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    void onRefresh();
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onRefresh, open]);

  return (
    <>
      <div className={`chatapp-device-use-control is-${mode}`} aria-label="Device Use">
        <button
          aria-haspopup="dialog"
          aria-label="Apri impostazioni Device Use"
          className="chatapp-device-use-control__settings"
          onClick={() => setOpen(true)}
          ref={buttonRef}
          title="Impostazioni Device Use"
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-rounded">desktop_windows</span>
        </button>
        <div className="chatapp-device-use-control__modes" role="radiogroup" aria-label="Modalità Device Use">
          {(["off", "on", "full"] as DeviceUseMode[]).map((option) => (
            <button
              aria-checked={mode === option}
              className={mode === option ? "is-active" : ""}
              disabled={busy || (locked && option !== "off" && option !== mode)}
              key={option}
              onClick={() => onModeChange(option)}
              role="radio"
              title={locked && option !== "off" && option !== mode
                ? "Avvia una nuova chat per cambiare modalità"
                : modeLabel(option)}
              type="button"
            >
              {option === "off" ? "Off" : option === "on" ? "On" : "Full"}
            </button>
          ))}
        </div>
      </div>
      {open ? createPortal(
        <div className="chatapp-usage-modal-backdrop" onMouseDown={() => setOpen(false)}>
          <DeviceUseSettingsModal
            busy={busy}
            mode={mode}
            onClose={() => { setOpen(false); buttonRef.current?.focus(); }}
            onConfigure={onConfigure}
            onRefresh={onRefresh}
            onRequestPermission={onRequestPermission}
            snapshot={snapshot}
            titleId={titleId}
          />
        </div>,
        document.body,
      ) : null}
    </>
  );
}

function DeviceUseSettingsModal({
  busy,
  mode,
  onClose,
  onConfigure,
  onRefresh,
  onRequestPermission,
  snapshot,
  titleId,
}: {
  busy: boolean;
  mode: DeviceUseMode;
  onClose: () => void;
  onConfigure: (settings: NativeDeviceUseSnapshot["settings"]) => Promise<void>;
  onRefresh: () => Promise<NativeDeviceUseSnapshot>;
  onRequestPermission: (permission: DeviceUsePermission) => void;
  snapshot: NativeDeviceUseSnapshot;
  titleId: string;
}) {
  const [selectedApp, setSelectedApp] = useState(snapshot.settings.selectedApp);
  const [additionalApps, setAdditionalApps] = useState(snapshot.settings.additionalApps);
  const [consentMode, setConsentMode] = useState<DeviceUseConsentMode>(snapshot.settings.consentMode);
  const [saved, setSaved] = useState(false);
  const settingsLocked = mode !== "off" || busy;

  useEffect(() => {
    setSelectedApp(snapshot.settings.selectedApp);
    setAdditionalApps(snapshot.settings.additionalApps);
    setConsentMode(snapshot.settings.consentMode);
  }, [snapshot.settings]);

  const dirty = selectedApp !== snapshot.settings.selectedApp
    || consentMode !== snapshot.settings.consentMode
    || [...additionalApps].sort().join("\0") !== [...snapshot.settings.additionalApps].sort().join("\0");

  return (
    <section
      aria-labelledby={titleId}
      aria-modal="true"
      className="chatapp-usage-modal chatapp-device-use-modal"
      onMouseDown={(event) => event.stopPropagation()}
      role="dialog"
    >
      <header className="chatapp-usage-modal__header">
        <div>
          <p className="chatapp-usage-modal__eyebrow">Maverick per macOS</p>
          <h2 id={titleId}>Device Use</h2>
        </div>
        <button aria-label="Chiudi impostazioni Device Use" className="chatapp-usage-modal__close" onClick={onClose} type="button">
          <span aria-hidden="true" className="material-symbols-rounded">close</span>
        </button>
      </header>

      <section className={`chatapp-device-use-modal__mode is-${mode}`}>
        <span className="material-symbols-rounded" aria-hidden="true">{mode === "full" ? "bolt" : mode === "on" ? "desktop_windows" : "power_settings_new"}</span>
        <div>
          <strong>{modeLabel(mode)}</strong>
          <p>{modeDescription(mode)}</p>
        </div>
      </section>

      <section className="chatapp-usage-modal__section">
        <div className="chatapp-device-use-modal__section-heading">
          <div><h3>Limiti della modalità On</h3><p>Full ignora queste impostazioni.</p></div>
          <button className="chatapp-device-use-modal__refresh" disabled={busy} onClick={() => { void onRefresh(); }} type="button">Aggiorna</button>
        </div>
        <label className="chatapp-device-use-modal__field">
          <span>App iniziale</span>
          <select disabled={settingsLocked} onChange={(event) => {
            const value = event.target.value;
            setSelectedApp(value);
            setAdditionalApps((current) => current.filter((item) => item !== value));
            setSaved(false);
          }} value={selectedApp}>
            <option value="">Scegli un'app aperta</option>
            {snapshot.apps.map((app) => <option key={app.bundleId} value={app.bundleId}>{app.name}</option>)}
          </select>
        </label>
        <fieldset className="chatapp-device-use-modal__fieldset" disabled={settingsLocked}>
          <legend>Altre app consentite</legend>
          <div className="chatapp-device-use-modal__app-list">
            {snapshot.apps.filter((app) => app.bundleId !== selectedApp).map((app) => (
              <label key={app.bundleId}>
                <input checked={additionalApps.includes(app.bundleId)} onChange={(event) => {
                  setAdditionalApps((current) => event.target.checked
                    ? [...new Set([...current, app.bundleId])]
                    : current.filter((item) => item !== app.bundleId));
                  setSaved(false);
                }} type="checkbox" />
                <span>{app.name}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="chatapp-device-use-modal__fieldset" disabled={settingsLocked}>
          <legend>Conferme</legend>
          <div className="chatapp-device-use-modal__radios">
            <Radio label="Ogni azione" checked={consentMode === "perAction"} onChange={() => { setConsentMode("perAction"); setSaved(false); }} />
            <Radio label="Una per incarico, senza limite" checked={consentMode === "perTask"} onChange={() => { setConsentMode("perTask"); setSaved(false); }} />
          </div>
        </fieldset>
        <button
          className="chat-ui-button chat-ui-button--primary chatapp-device-use-modal__save"
          disabled={settingsLocked || !dirty || !selectedApp}
          onClick={() => { void onConfigure({ selectedApp, additionalApps, consentMode }).then(() => setSaved(true)); }}
          type="button"
        >
          {saved ? "Salvate" : "Salva impostazioni On"}
        </button>
        {mode !== "off" ? <p className="chatapp-device-use-modal__hint">Spegni Device Use prima di cambiare i limiti.</p> : null}
      </section>

      <section className="chatapp-usage-modal__section">
        <h3>Permessi macOS</h3>
        <div className="chatapp-device-use-modal__permissions">
          <Permission name="Schermo" granted={snapshot.permissions.screen} onRequest={() => onRequestPermission("screen")} disabled={settingsLocked} />
          <Permission name="Accessibilità" granted={snapshot.permissions.accessibility} onRequest={() => onRequestPermission("accessibility")} disabled={settingsLocked} />
          <Permission name="Input" granted={snapshot.permissions.input} onRequest={() => onRequestPermission("input")} disabled={settingsLocked} />
        </div>
      </section>

      <p className="chatapp-usage-modal__note">
        Full è realmente illimitato nell'executor: tutte le app e superfici, campi protetti, azioni sensibili e numero di richieste sono senza conferme o tetti. Solo Off/Stop e il blocco schermo revocano l'autorità; chiusura dell'app o perdita di rete restano condizioni fisiche inevitabili.
      </p>
      {snapshot.notice ? <p className="chatapp-device-use-modal__notice">{snapshot.notice}</p> : null}
    </section>
  );
}

function Radio({ checked, label, onChange }: { checked: boolean; label: string; onChange: () => void }) {
  return <label><input checked={checked} onChange={onChange} type="radio" /><span>{label}</span></label>;
}

function Permission({
  disabled,
  granted,
  name,
  onRequest,
}: {
  disabled: boolean;
  granted: boolean;
  name: string;
  onRequest: () => void;
}) {
  return <article>
    <div><span>{name}</span><strong className={granted ? "is-granted" : ""}>{granted ? "Concesso" : "Da concedere"}</strong></div>
    {!granted ? <button disabled={disabled} onClick={onRequest} type="button">Concedi</button> : null}
  </article>;
}

function modeLabel(mode: DeviceUseMode): string {
  if (mode === "full") return "Full — controllo totale";
  if (mode === "on") return "On — limiti configurati";
  return "Off — disattivato";
}

function modeDescription(mode: DeviceUseMode): string {
  if (mode === "full") return "Nessuna allowlist, conferma o soglia. Si ferma solo con Stop/Off o al blocco schermo.";
  if (mode === "on") return "Usa app e conferme definite qui sotto.";
  return "Nessuna schermata o azione del Mac è disponibile alla chat.";
}
