import { AppDependenciesPayload, DependencyResolutionItem } from "../api";
import { Badge, Button, EmptyPanel, LoadingPanel } from "../ui";

export function AppDependencySetup({
  dependencies,
  error,
  isLoading,
  isOpen = false,
  onClose,
  onOpenAppStore,
  onSave,
}: {
  dependencies: AppDependenciesPayload | null;
  error: string | null;
  isLoading: boolean;
  isOpen?: boolean;
  onClose?: () => void;
  onOpenAppStore: (interfaceId: string) => void;
  onSave: (alias: string, providerAppIds: string[]) => Promise<void>;
}) {
  const shouldShow = isLoading || Boolean(error) || isOpen || Boolean(dependencies && dependencies.status !== "resolved");
  if (!shouldShow) {
    return null;
  }
  if (isLoading) {
    return (
      <div className="bs-dependency-overlay">
        <LoadingPanel description="Controllo le interfacce richieste da questa app." title="Setup app" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="bs-dependency-overlay">
        <EmptyPanel description={error} title="Setup non disponibile" />
      </div>
    );
  }
  if (!dependencies) {
    return null;
  }
  return (
    <div className="bs-dependency-overlay" role="dialog" aria-label="Setup dipendenze app">
      <section className="bs-dependency-panel">
        <header className="bs-dependency-panel__header">
          <span className="material-symbols-rounded" aria-hidden="true">hub</span>
          <span>
            <p className="bs-eyebrow">{dependencies.status === "resolved" ? "Collegamenti app" : "Setup richiesto"}</p>
            <h2>Collega le app provider</h2>
          </span>
          <DependencyPanelCloseButton isVisible={isOpen && dependencies.status === "resolved"} onClose={onClose} />
        </header>
        <div className="bs-dependency-list">
          {dependencies.dependencies.map((item) => (
            <DependencyRow
              item={item}
              key={item.alias}
              onOpenAppStore={onOpenAppStore}
              onSave={onSave}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

function DependencyPanelCloseButton({
  isVisible,
  onClose,
}: {
  isVisible: boolean;
  onClose?: () => void;
}) {
  if (!isVisible || !onClose) {
    return null;
  }
  return (
    <button className="bs-dependency-panel__close" onClick={onClose} type="button" aria-label="Chiudi collegamenti app" title="Chiudi">
      <span className="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  );
}

function DependencyRow({
  item,
  onOpenAppStore,
  onSave,
}: {
  item: DependencyResolutionItem;
  onOpenAppStore: (interfaceId: string) => void;
  onSave: (alias: string, providerAppIds: string[]) => Promise<void>;
}) {
  const selected = new Set(item.selected_provider_app_ids);
  const isBlocked = ["missing_provider", "unresolved", "stale", "invalid_selection"].includes(item.status);
  return (
    <article className={`bs-dependency-row ${isBlocked ? "is-blocked" : ""}`}>
      <header>
        <span>
          <strong>{item.alias}</strong>
          <small>{item.interface} {item.version}</small>
        </span>
        <Badge tone={dependencyTone(item.status)}>{item.status}</Badge>
      </header>
      <p>{item.description}</p>
      {item.blocked_reason ? <p className="bs-dependency-row__reason">{item.blocked_reason}</p> : null}
      {item.stale_provider_app_ids.length ? (
        <p className="bs-dependency-row__reason">Selezioni non più valide: {item.stale_provider_app_ids.join(", ")}</p>
      ) : null}
      {item.candidates.length ? (
        <div className="bs-dependency-candidates">
          {item.candidates.map((candidate) => {
            const checked = selected.has(candidate.app_id);
            return (
              <label className="bs-dependency-candidate" key={candidate.app_id}>
                <input
                  checked={checked}
                  name={item.alias}
                  onChange={(event) => {
                    if (item.cardinality === "one") {
                      onSave(item.alias, event.currentTarget.checked ? [candidate.app_id] : []);
                      return;
                    }
                    const next = new Set(selected);
                    if (event.currentTarget.checked) {
                      next.add(candidate.app_id);
                    } else {
                      next.delete(candidate.app_id);
                    }
                    onSave(item.alias, Array.from(next));
                  }}
                  type={item.cardinality === "one" ? "radio" : "checkbox"}
                />
                <span>
                  <strong>{candidate.name || candidate.app_id}</strong>
                  <small>{candidate.app_id} · {candidate.interface_version}</small>
                </span>
              </label>
            );
          })}
        </div>
      ) : (
        <Button onClick={() => onOpenAppStore(item.interface)} size="sm" variant="primary">
          Apri App Store
        </Button>
      )}
    </article>
  );
}

function dependencyTone(status: string): "neutral" | "primary" | "success" | "warning" | "danger" {
  if (status === "resolved" || status === "optional_unset") {
    return "success";
  }
  if (status === "missing_provider" || status === "stale" || status === "invalid_selection") {
    return "danger";
  }
  return "warning";
}
