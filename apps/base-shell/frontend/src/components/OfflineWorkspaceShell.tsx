import type { MaverickConnectivityState } from "../connectivity";
import type { SidebarMode } from "../session";
import type { ShellPwaUpdateState } from "../pwa";
import { OfflineIndicator } from "./OfflineIndicator";

export function OfflineWorkspaceShell({
  connectivity,
  onOpenLocalContent,
  sidebarMode,
  update,
}: {
  connectivity: MaverickConnectivityState;
  onOpenLocalContent: () => void;
  sidebarMode: SidebarMode;
  update: ShellPwaUpdateState;
}) {
  const expanded = sidebarMode === "fixed";
  return (
    <main className={`bs-shell bs-offline-workspace-shell is-sidebar-mode-${sidebarMode}`}>
      <aside className={`bs-offline-workspace-shell__sidebar ${expanded ? "is-expanded" : "is-compact"}`} aria-label="Stato connessione">
        <OfflineIndicator
          connectivity={connectivity}
          mode={expanded ? "expanded" : "compact"}
          onOpen={onOpenLocalContent}
          updateAvailable={update.available}
        />
        {expanded ? <img alt="Maverick" className="bs-offline-workspace-shell__logo" src="/apps/base-shell/sidebar-logo.svg" /> : null}
      </aside>
      <section className="bs-offline-workspace-shell__content" aria-labelledby="offline-content-title">
        <div className="bs-offline-workspace-shell__card">
          <span aria-hidden="true" className="material-symbols-rounded">devices</span>
          <h1 id="offline-content-title">Contenuto non disponibile sul dispositivo</h1>
          <p>La shell è pronta, ma questa app non ha un contenuto locale autorizzato. Riconnettiti per usare prompt, modelli, agenti, tool e azioni remote.</p>
          <button onClick={onOpenLocalContent} type="button">Gestisci contenuti locali</button>
        </div>
      </section>
    </main>
  );
}
