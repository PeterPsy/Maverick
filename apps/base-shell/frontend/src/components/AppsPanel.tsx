import { AppRegistryItem } from "../api";
import { shellVisibleApps } from "../navigation";
import { AppLogo } from "./AppLogo";

export function AppsPanel({
  apps,
  error,
  isLoading,
  onOpenApp,
}: {
  apps: AppRegistryItem[];
  error: string | null;
  isLoading: boolean;
  onOpenApp: (appId: string) => void;
}) {
  const visibleApps = shellVisibleApps(apps);
  if (isLoading) {
    return <EmptyPanel description="Recupero il registry corrente del sistema." title="Carico le app installate" />;
  }
  if (error) {
    return <EmptyPanel description={error} title="Impossibile leggere il registry app" />;
  }
  if (!visibleApps.length) {
    return <EmptyPanel description="Quando il registry contiene app installate, le vedrai qui." title="Nessuna app installata" />;
  }
  return (
    <section className="bs-app-grid-panel">
      <div className="bs-app-grid-panel__header">
        <p className="bs-eyebrow">App Registry</p>
        <h2 className="bs-app-grid-panel__title">App installate</h2>
        <p className="bs-app-grid-panel__description">Le app abilitate nel workspace corrente compaiono qui e vengono aperte tramite mount v3.</p>
      </div>
      <div className="bs-app-grid">
        {visibleApps.map((app) => (
          <button className="bs-app-card" key={app.app_id} onClick={() => onOpenApp(app.app_id)} type="button">
            <span className="bs-app-card__header">
              <AppLogo app={app} className="bs-app-logo--card" />
              <span>
                <span className="bs-app-card__title">{app.name}</span>
                <span className="bs-app-card__description">{app.description || "App montata dal registry v3."}</span>
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

function EmptyPanel({ description, title }: { description: string; title: string }) {
  return (
    <section className="bs-empty-panel">
      <div className="bs-empty-panel__surface">
        <p className="bs-empty-panel__title">{title}</p>
        <p className="bs-empty-panel__description">{description}</p>
      </div>
    </section>
  );
}
