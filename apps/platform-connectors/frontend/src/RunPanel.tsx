import { useState } from "react";
import {
  active,
  shellHref,
  dateLabel,
  type Collection,
  type Perform,
  type Run,
  type State,
} from "./api";
type Props = {
  selected: Run;
  state: State;
  busy: boolean;
  perform: Perform;
  onRun: (run: Run) => void;
  onCollection: (collection: Collection) => void;
};
export function RunPanel({
  selected,
  state,
  busy,
  perform,
  onRun,
  onCollection,
}: Props) {
  const [saveOpen, setSaveOpen] = useState(false);
  const [collectionTitle, setCollectionTitle] = useState("");
  return (
    <section className="run-summary">
      <div className="board-header">
        <div>
          <h2>
            {active(selected)
              ? "Observing your source…"
              : selected.status === "failed"
                ? "Observation stopped"
                : selected.status === "cancelled"
                  ? "Observation cancelled"
                  : "Source observations"}
          </h2>
          <p className="meta">
            {selected.status} · {selected.phase.replaceAll(".", " · ")} ·{" "}
            {dateLabel(selected.created_at)}
          </p>
        </div>
        <div className="actions">
          {active(selected) ? (
            <button
              disabled={busy}
              onClick={() =>
                void perform({ action: "run.cancel", id: selected.id })
              }
            >
              Cancel
            </button>
          ) : ["completed", "failed", "cancelled"].includes(selected.status) &&
            !!(
              selected.result.items?.length ||
              selected.result.context_items?.length
            ) ? (
            <button
              onClick={() => {
                setSaveOpen(!saveOpen);
                setCollectionTitle(
                  `${state.sources.find((s) => s.id === selected.source)?.name} · ${dateLabel(selected.created_at)}`,
                );
              }}
            >
              Save collection
            </button>
          ) : state.sources
              .find((s) => s.id === selected.source)
              ?.operations.includes(selected.operation) ? (
            <button
              disabled={busy}
              onClick={async () => {
                const next = await perform<{ run: Run }>({
                  action: "run.start",
                  source: selected.source,
                  operation: selected.operation,
                  parameters: selected.parameters,
                });
                if (next) onRun(next.run);
              }}
            >
              Retry
            </button>
          ) : null}
        </div>
      </div>
      {active(selected) && (
        <div className="progress" role="status">
          <span />
          Keep the shared tab and connector window available. Results update as
          observations finish.
        </div>
      )}
      {selected.error && <p className="notice error">{selected.error}</p>}
      {selected.result.coverage && (
        <p className="coverage">
          {selected.result.coverage}
          {selected.result.stop_reason &&
            ` · Stopped at ${selected.result.stop_reason.replaceAll("_", " ")}`}
        </p>
      )}
      {selected.result.text && (
        <details className="observation-text">
          <summary>Read source response</summary>
          <p className="source-text">{selected.result.text}</p>
        </details>
      )}
      {selected.result.file && (
        <a
          className="button primary"
          href={shellHref(selected.result.file.deep_link)}
          target="_top"
        >
          Open exported file in Storage ↗
        </a>
      )}
      {saveOpen && (
        <form
          className="save-form"
          onSubmit={async (e) => {
            e.preventDefault();
            const result = await perform<{ collection: Collection }>({
              action: "collection.save",
              run_id: selected.id,
              title: collectionTitle,
            });
            if (result) {
              onCollection(result.collection);
              setSaveOpen(false);
            }
          }}
        >
          <input
            aria-label="Collection title"
            value={collectionTitle}
            required
            maxLength={160}
            onChange={(e) => setCollectionTitle(e.target.value)}
          />
          <button className="primary" disabled={busy}>
            Save
          </button>
          <button type="button" onClick={() => setSaveOpen(false)}>
            Cancel
          </button>
        </form>
      )}
    </section>
  );
}
