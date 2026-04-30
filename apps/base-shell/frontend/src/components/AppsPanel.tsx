import { AppRegistryItem } from "../api";
import { appStatusTone, shellVisibleApps } from "../navigation";
import { Badge, Button, EmptyPanel, LoadingPanel } from "../ui";
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
    return <LoadingPanel description="Recupero il registry corrente del sistema." title="Carico le app installate" />;
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
        <p className="bs-app-grid-panel__description">Le app abilitate nel workspace corrente compaiono qui e vengono aperte tramite mount.</p>
      </div>
      <div className="bs-app-grid">
        {visibleApps.map((app) => (
          <article className="bs-app-card" key={app.app_id}>
            <button className="bs-app-card__open" onClick={() => onOpenApp(app.app_id)} type="button">
              <AppLogo app={app} className="bs-app-logo--card" />
              <span className="bs-app-card__copy">
                <span className="bs-app-card__title">{app.name}</span>
                <span className="bs-app-card__description">{app.description || "App montata dal registry."}</span>
              </span>
            </button>
            <div className="bs-app-card__meta">
              <Badge tone={appStatusTone(app.status)}>{app.status}</Badge>
              <Badge>{app.version}</Badge>
            </div>
            <div className="bs-app-card__actions">
              <Button onClick={() => onOpenApp(app.app_id)} size="sm" variant="primary">
                Apri
              </Button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
