import { PlatformSettings } from "../api";
import { Dialog, Surface } from "../ui";
import { TutorialDialog } from "./TutorialDialog";

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
      <TutorialDialog onClose={onClose} open={activeDialog === "tutorial"} />
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
