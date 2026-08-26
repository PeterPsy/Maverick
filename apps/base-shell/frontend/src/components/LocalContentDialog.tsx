import type { MaverickConnectivityState } from "../connectivity";
import { formatLastSuccessfulSync } from "../connectivity";
import type { ShellPwaUpdateState } from "../pwa";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";

export function LocalContentDialog({
  connectivity,
  onApplyUpdate,
  onClose,
  onRecover,
  onRetry,
  open,
  update,
}: {
  connectivity: MaverickConnectivityState;
  onApplyUpdate: () => void;
  onClose: () => void;
  onRecover: () => void;
  onRetry: () => void;
  open: boolean;
  update: ShellPwaUpdateState;
}) {
  const freshness = connectivity.freshness === "fresh"
    ? "Aggiornato"
    : connectivity.freshness === "expired"
      ? "Scaduto"
      : "Non verificato";
  const syncState = connectivity.syncState === "idle"
    ? "Inattivo"
    : connectivity.syncState === "checking"
      ? "Aggiornamento"
      : connectivity.syncState === "error"
        ? "Errore"
        : "Offline";

  return (
    <Dialog
      description="Stato della shell e dei contenuti conservati localmente su questo dispositivo."
      onClose={onClose}
      open={open}
      panelClassName="bs-local-content-dialog"
      title="Contenuti sul dispositivo"
    >
      <div className="bs-local-content-dialog__body">
        <dl className="bs-local-content-dialog__status">
          <div><dt>Stato</dt><dd>{connectivity.onlineActionsBlocked ? "Offline" : "Online"}</dd></div>
          <div><dt>Ultima sincronizzazione</dt><dd>{formatLastSuccessfulSync(connectivity.lastSuccessfulAt)}</dd></div>
          <div><dt>Sorgente</dt><dd>{connectivity.source === "network" ? "Rete" : "Dispositivo"}</dd></div>
          <div><dt>Freschezza</dt><dd>{freshness}</dd></div>
          <div><dt>Sincronizzazione</dt><dd>{syncState}</dd></div>
        </dl>
        <section className="bs-local-content-dialog__section" aria-labelledby="local-shell-title">
          <div>
            <h4 id="local-shell-title">Shell Maverick</h4>
            <p>Branding e interfaccia di base verificati per questa build.</p>
          </div>
          <span className="bs-local-content-dialog__available">Disponibile</span>
        </section>
        <section className="bs-local-content-dialog__notice" aria-label="Limiti offline">
          <span aria-hidden="true" className="material-symbols-rounded">shield_lock</span>
          <p>Nessun dato privato delle app è disponibile offline in M2. Modelli, agenti, tool, prompt e azioni remote richiedono la rete.</p>
        </section>
        {update.available ? (
          <section className="bs-local-content-dialog__update" aria-live="polite">
            <div>
              <strong>Aggiornamento della shell disponibile</strong>
              <p>La nuova build verrà attivata e la shell sarà ricaricata.</p>
            </div>
            <Button loading={update.applying} onClick={onApplyUpdate} variant="primary">Aggiorna</Button>
          </section>
        ) : null}
        {update.recovery === "failed" ? <p className="bs-local-content-dialog__error">La verifica della cache non è riuscita.</p> : null}
        {update.recovery === "recovered" ? <p aria-live="polite" className="bs-local-content-dialog__success">Cache della shell verificata.</p> : null}
        <div className="bs-local-content-dialog__actions">
          <Button onClick={onRetry}>Verifica rete</Button>
          <Button loading={update.recovery === "recovering"} onClick={onRecover}>Verifica cache</Button>
        </div>
      </div>
    </Dialog>
  );
}
