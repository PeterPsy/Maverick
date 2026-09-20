import { useEffect, useRef, useState } from "react";
import type { AppRegistryItem } from "../api";
import type { MaverickFrameScope } from "../iframePolicy";
import type { ShellThemeState } from "../theme";
import { APP_STORE_APP_ID, SETTINGS_APP_ID } from "../navigation";
import { AppLogo } from "./AppLogo";
import { WidgetSlot } from "./WidgetSlot";

export function externalSettingsProvider(apps: AppRegistryItem[], owner?: AppRegistryItem) {
  // App-owned live surfaces need not delegate to the shared static publisher.
  if (owner?.provides.some(item => item.interface === "app.external.surfaces.settings" && item.version === "1")) return owner;
  const providers = apps.filter(app => app.provides.some(item => item.interface === "external.surfaces.settings" && item.version === "1"));
  return providers.length === 1 ? providers[0] : null;
}

export function AppSettingsDialog({ app, apps, frameScope, isPinned, isLastPinned, onClose, onOpenApp, onTogglePin, shellTheme }: {
  app: AppRegistryItem;
  apps: AppRegistryItem[];
  frameScope: MaverickFrameScope;
  isPinned: boolean;
  isLastPinned: boolean;
  onClose: () => void;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  onTogglePin: () => Promise<void>;
  shellTheme: ShellThemeState;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const alive = useRef(true);
  const [section, setSection] = useState<"general" | "external">("general");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const provider = externalSettingsProvider(apps, app);
  useEffect(() => {
    alive.current = true;
    const node = dialog.current;
    node?.showModal();
    return () => { alive.current = false; node?.close(); };
  }, []);

  function close() {
    // Close while still mounted so the browser restores focus to the opener.
    dialog.current?.close();
    onClose();
  }

  async function togglePin() {
    setBusy(true); setError("");
    try { await onTogglePin(); }
    catch (cause) { if (alive.current) setError(cause instanceof Error ? cause.message : "Impossibile salvare."); }
    finally { if (alive.current) setBusy(false); }
  }

  const slotProps = {
    activeWorkspaceId: frameScope.workspaceId,
    content: { app_id: app.app_id, app_name: app.name },
    frameScope, hostAppId: "base-shell", shellTheme,
    onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => { close(); onOpenApp(appId, params); },
  };
  return <dialog ref={dialog} className="bs-app-settings" aria-labelledby="bs-app-settings-title" onCancel={event => { event.preventDefault(); close(); }}>
    <header className="bs-app-settings__header">
      <AppLogo app={app} className="bs-app-settings__logo" />
      <div><p>Impostazioni app</p><h2 id="bs-app-settings-title">{app.name}</h2></div>
      <button type="button" className="bs-app-settings__close" aria-label="Chiudi impostazioni app" onClick={close} autoFocus>
        <span aria-hidden="true" className="material-symbols-rounded">close</span>
      </button>
    </header>
    <nav className="bs-app-settings__tabs" aria-label="Sezioni impostazioni">
      <button type="button" aria-pressed={section === "general"} onClick={() => setSection("general")}>Generali</button>
      <button type="button" aria-pressed={section === "external"} onClick={() => setSection("external")}>Superfici esterne</button>
    </nav>
    <div className={`bs-app-settings__body${section === "external" ? " bs-app-settings__body--external" : ""}`} key={section}>
      {section === "general" ? <>
        <div className="bs-app-settings__summary"><p>{app.description}</p><small>Versione {app.version} · {app.publisher}</small></div>
        {app.frontend_role === "workspace" && ![APP_STORE_APP_ID, SETTINGS_APP_ID].includes(app.app_id) && <div>
          <label className="bs-app-settings__pin"><span>Mostra nella barra delle app</span><input type="checkbox" checked={isPinned} disabled={busy || isLastPinned} onChange={togglePin} aria-describedby={isLastPinned ? "bs-app-settings-pin-hint" : undefined} /></label>
          {isLastPinned && <small id="bs-app-settings-pin-hint">Mantieni almeno un’app nella barra.</small>}
        </div>}
        {error && <p role="alert">{error}</p>}
        <WidgetSlot {...slotProps} contentKind="shell.app.settings" preferredOwnerAppId={app.app_id}
          label={`Impostazioni di ${app.name}`} emptyMessage="Questa app non espone altre impostazioni." />
      </> : provider ? <WidgetSlot {...slotProps} contentKind="shell.app.external.surfaces" preferredOwnerAppId={provider.app_id}
        label={`Superfici esterne di ${app.name}`} emptyMessage="Gestione delle superfici esterne non disponibile." />
        : <p className="bs-app-settings__empty">Nessun gestore univoco delle superfici esterne è disponibile in questo workspace.</p>}
    </div>
  </dialog>;
}
