import { useState } from "react";
import {
  type Collection,
  type Connection,
  type Perform,
  type Run,
} from "./api";
type Props = {
  collection: Collection;
  connections: Connection[];
  busy: boolean;
  perform: Perform;
  onRun: (run: Run) => void;
  onCollection: (collection: Collection | null) => void;
};
export function CollectionPanel({
  collection,
  connections,
  busy,
  perform,
  onRun,
  onCollection,
}: Props) {
  const [collectionTitle, setCollectionTitle] = useState(collection.title);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const sessions = connections.filter(
    (c) =>
      c.platform === collection.source &&
      c.status === "connected" &&
      (!c.expires_at || c.expires_at > Date.now() / 1000),
  );
  const original = String(collection.parameters.session_id || "");
  const session =
    sessions.find((c) => c.session_id === original)?.session_id ||
    sessions[0]?.session_id;
  return (
    <section className="run-summary">
      <div className="board-header">
        <div>
          <h2>{collection.title}</h2>
          <p className="meta">{collection.total} saved observations</p>
        </div>
        <div className="actions">
          <button
            disabled={busy}
            onClick={async () => {
              const r = await perform<{ run: Run }>({
                action: "collection.refresh",
                id: collection.id,
                ...(session ? { session_id: session } : {}),
              });
              if (r) onRun(r.run);
            }}
          >
            Refresh source
          </button>
          <button
            disabled={busy}
            onClick={async () => {
              const r = await perform<{ run: Run }>({
                action: "collection.export",
                id: collection.id,
                format: "markdown",
              });
              if (r) {
                onRun(r.run);
              }
            }}
          >
            Export Markdown
          </button>
          <button
            disabled={busy}
            onClick={async () => {
              const r = await perform<{ run: Run }>({
                action: "collection.export",
                id: collection.id,
                format: "json",
              });
              if (r) {
                onRun(r.run);
              }
            }}
          >
            Export JSON
          </button>
        </div>
      </div>
      <details>
        <summary>Collection settings</summary>
        <div className="save-form">
          <input
            aria-label="Rename collection"
            maxLength={160}
            value={collectionTitle}
            onChange={(e) => setCollectionTitle(e.target.value)}
          />
          <button
            onClick={async () => {
              const r = await perform<{ collection: Collection }>({
                action: "collection.rename",
                id: collection.id,
                title: collectionTitle,
              });
              if (r) onCollection(r.collection);
            }}
          >
            Rename
          </button>
          <button className="danger" onClick={() => setDeleteOpen(true)}>
            Delete collection
          </button>
        </div>
        {deleteOpen && (
          <div className="notice">
            <span>Delete “{collection.title}” and its saved observations?</span>
            <button
              className="danger"
              onClick={async () => {
                const r = await perform({
                  action: "collection.delete",
                  id: collection.id,
                });
                if (r) {
                  onCollection(null);
                  setDeleteOpen(false);
                }
              }}
            >
              Delete
            </button>
            <button onClick={() => setDeleteOpen(false)}>
              Keep collection
            </button>
          </div>
        )}
      </details>
    </section>
  );
}
