import type { DeviceUseMode } from "../lib/deviceUse";

export function DeviceUseControl({
  busy,
  locked,
  mode,
  pinnedMode = null,
  onModeChange,
}: {
  busy: boolean;
  locked: boolean;
  mode: DeviceUseMode;
  pinnedMode?: Exclude<DeviceUseMode, "off"> | null;
  onModeChange: (mode: DeviceUseMode) => void;
}) {
  const active = mode !== "off";
  const cannotEnable = locked && pinnedMode !== "full";

  return (
    <button
      aria-label={active ? "Disattiva PC use" : "Attiva PC use"}
      aria-pressed={active}
      className={`chatapp-composer__tool-button chatapp-device-use-control ${active ? "is-active" : ""}`}
      disabled={busy || (!active && cannotEnable)}
      onClick={() => onModeChange(active ? "off" : "full")}
      title={active ? "Disattiva l'accesso al Mac"
        : cannotEnable ? "Avvia una nuova chat per attivare PC use con accesso completo"
          : "Attiva PC use con accesso completo al Mac"}
      type="button"
    >
      <span aria-hidden="true" className="material-symbols-rounded">desktop_windows</span>
      {active ? <span className="chatapp-device-use-control__label">PC use</span> : null}
    </button>
  );
}
