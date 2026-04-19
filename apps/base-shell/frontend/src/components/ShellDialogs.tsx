import { Dialog, Surface } from "../ui";

type ShellDialog = "settings" | "tutorial" | null;

export function ShellDialogs({ activeDialog, onClose }: { activeDialog: ShellDialog; onClose: () => void }) {
  return (
    <>
      <Dialog
        description="Una guida breve alle superfici già disponibili nella shell v3."
        onClose={onClose}
        open={activeDialog === "tutorial"}
        title="Tutorial"
      >
        <div className="bs-dialog-grid">
          <Surface>
            <p className="bs-dialog-card__eyebrow">App registry</p>
            <h4 className="bs-dialog-card__title">Le app arrivano dal core.</h4>
            <p className="bs-dialog-card__copy">
              La shell mostra solo app abilitate dal registry v3 e monta i frontend dichiarati dal contract.
            </p>
          </Surface>
          <Surface>
            <p className="bs-dialog-card__eyebrow">Workspace</p>
            <h4 className="bs-dialog-card__title">La shell non possiede dati core.</h4>
            <p className="bs-dialog-card__copy">
              Le preferenze locali restano nel browser; dati app e runtime restano nelle superfici app/core dedicate.
            </p>
          </Surface>
          <Surface>
            <p className="bs-dialog-card__eyebrow">Agents</p>
            <h4 className="bs-dialog-card__title">MCP, CLI e skills vivono fuori dalla UI.</h4>
            <p className="bs-dialog-card__copy">
              Questa app visualizza e ospita; gli agent usano le superfici dichiarate dai singoli app contract.
            </p>
          </Surface>
        </div>
      </Dialog>
      <Dialog
        description="Impostazioni locali disponibili senza introdurre dipendenze da domini v3 non ancora pubblici."
        onClose={onClose}
        open={activeDialog === "settings"}
        title="Settings"
      >
        <div className="bs-settings-list">
          <Surface>
            <p className="bs-dialog-card__eyebrow">Storage locale</p>
            <h4 className="bs-dialog-card__title">Sessione shell</h4>
            <p className="bs-dialog-card__copy">
              App attiva, menu laterale e app fissate sono salvate in `localStorage` del browser.
            </p>
          </Surface>
          <Surface>
            <p className="bs-dialog-card__eyebrow">Backend</p>
            <h4 className="bs-dialog-card__title">Nessuna impostazione server qui.</h4>
            <p className="bs-dialog-card__copy">
              Provider, recovery, utenti e workspace saranno esposti solo tramite app o API v3 dedicate.
            </p>
          </Surface>
        </div>
      </Dialog>
    </>
  );
}

export type { ShellDialog };
