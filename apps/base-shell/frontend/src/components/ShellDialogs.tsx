import { PlatformSettings } from "../api";
import { Dialog, Surface } from "../ui";

type ShellDialog = "settings" | "tutorial" | null;

export function ShellDialogs({
  activeDialog,
  onClose,
  onLogout,
  settings,
}: {
  activeDialog: ShellDialog;
  onClose: () => void;
  onLogout: () => void;
  settings: PlatformSettings | null;
}) {
  const governance = settings?.workspace.governance || {};
  return (
    <>
      <Dialog
        description="Primi passi della shell v3: workspace, app montate e provider runtime."
        onClose={onClose}
        open={activeDialog === "tutorial"}
        title="Tutorial"
      >
        <div className="bs-dialog-grid">
          <Surface>
            <p className="bs-dialog-card__eyebrow">App registry</p>
            <h4 className="bs-dialog-card__title">Apri app dal registry.</h4>
            <p className="bs-dialog-card__copy">
              La griglia mostra solo app abilitate nel workspace attivo. Ogni frontend viene servito dal mount dichiarato nel contract.
            </p>
          </Surface>
          <Surface>
            <p className="bs-dialog-card__eyebrow">Workspace selector</p>
            <h4 className="bs-dialog-card__title">Cambia tenant senza ricaricare codice.</h4>
            <p className="bs-dialog-card__copy">
              Il selettore laterale cambia la sessione attiva sul core. Il registry e le app si riallineano al workspace scelto.
            </p>
          </Surface>
          <Surface>
            <p className="bs-dialog-card__eyebrow">Provider</p>
            <h4 className="bs-dialog-card__title">Codex è il backend runtime iniziale.</h4>
            <p className="bs-dialog-card__copy">
              La top bar mostra provider e runtime attivi. In seguito altri provider useranno la stessa superficie core.
            </p>
          </Surface>
        </div>
      </Dialog>
      <Dialog
        description="Stato reale letto dalle API core del workspace attivo."
        onClose={onClose}
        open={activeDialog === "settings"}
        title="Settings"
      >
        <div className="bs-settings-list">
          <Surface>
            <p className="bs-dialog-card__eyebrow">Utente</p>
            <h4 className="bs-dialog-card__title">{settings?.user.display_name || settings?.user.username || "Non disponibile"}</h4>
            <p className="bs-dialog-card__copy">{settings?.user.platform_role || "member"} · {settings?.workspace.name || "Workspace"}</p>
          </Surface>
          <Surface>
            <p className="bs-dialog-card__eyebrow">Provider</p>
            <h4 className="bs-dialog-card__title">{settings?.provider.active_provider.label || "Provider non caricato"}</h4>
            <p className="bs-dialog-card__copy">
              {settings?.provider.active_provider.default_model_family || "model"} · {settings?.runtime.sessions.length ?? 0} sessioni runtime
            </p>
          </Surface>
          <Surface>
            <p className="bs-dialog-card__eyebrow">Governance</p>
            <div className="bs-settings-flags">
              {Object.entries(governance).map(([key, value]) => (
                <span className={`bs-settings-flag ${value ? "is-on" : "is-off"}`} key={key}>
                  {key.replaceAll("_", " ")}
                </span>
              ))}
            </div>
          </Surface>
          <button className="bs-settings-logout" onClick={onLogout} type="button">
            Logout
          </button>
        </div>
      </Dialog>
    </>
  );
}

export type { ShellDialog };
