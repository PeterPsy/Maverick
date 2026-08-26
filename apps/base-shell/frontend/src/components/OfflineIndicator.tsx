import type { MaverickConnectivityState } from "../connectivity";
import { formatLastSuccessfulSync } from "../connectivity";

export function OfflineIndicator({
  connectivity,
  mode,
  onOpen,
  updateAvailable = false,
}: {
  connectivity: MaverickConnectivityState;
  mode: "compact" | "expanded";
  onOpen: () => void;
  updateAvailable?: boolean;
}) {
  const checking = connectivity.status === "checking" && connectivity.onlineActionsBlocked;
  const label = updateAvailable && !connectivity.onlineActionsBlocked
    ? "Aggiornamento disponibile"
    : checking
      ? "Verifica rete"
      : "Offline";
  const icon = updateAvailable && !connectivity.onlineActionsBlocked ? "system_update" : checking ? "sync" : "cloud_off";
  const accessibleLabel = mode === "compact"
    ? `${label} — apri contenuti sul dispositivo`
    : `${label}. Apri contenuti sul dispositivo`;

  return (
    <button
      aria-label={accessibleLabel}
      className={`bs-offline-indicator bs-offline-indicator--${mode} ${checking ? "is-checking" : ""} ${updateAvailable ? "has-update" : ""}`}
      data-maverick-connectivity={connectivity.onlineActionsBlocked ? connectivity.status : undefined}
      data-testid={`offline-indicator-${mode}`}
      onClick={onOpen}
      title={mode === "compact" ? accessibleLabel : undefined}
      type="button"
    >
      <span aria-hidden="true" className="material-symbols-rounded bs-offline-indicator__icon">{icon}</span>
      {mode === "expanded" ? (
        <span className="bs-offline-indicator__copy">
          <strong>{label}</strong>
          <small>Ultima sincronizzazione: {formatLastSuccessfulSync(connectivity.lastSuccessfulAt)}</small>
        </span>
      ) : null}
    </button>
  );
}
