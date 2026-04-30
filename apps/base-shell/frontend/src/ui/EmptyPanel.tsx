import { Surface } from "./Surface";

export function EmptyPanel({ description, title }: { description: string; title: string }) {
  return (
    <section className="bs-empty-panel">
      <Surface className="bs-empty-panel__surface">
        <p className="bs-empty-panel__title">{title}</p>
        <p className="bs-empty-panel__description">{description}</p>
      </Surface>
    </section>
  );
}

export function LoadingPanel({ description, title }: { description: string; title: string }) {
  return (
    <section className="bs-empty-panel">
      <Surface className="bs-empty-panel__surface">
        <div className="bs-loading-panel__indicator" aria-hidden="true">
          <span className="bs-ui-button__spinner" />
        </div>
        <p className="bs-empty-panel__title">{title}</p>
        <p className="bs-empty-panel__description">{description}</p>
      </Surface>
    </section>
  );
}
