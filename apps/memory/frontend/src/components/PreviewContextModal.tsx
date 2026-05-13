import { X } from "lucide-react";
import { labelForType, truncate } from "../format";

export type PreviewContextItem = {
  node_id?: string;
  title: string;
  summary?: string;
  body_text?: string;
  type?: string;
  relevance?: number;
  reason?: string;
};

type PreviewContextModalProps = {
  error: string;
  items: PreviewContextItem[];
  loading: boolean;
  open: boolean;
  query: string;
  onClose: () => void;
};

export function PreviewContextModal({ error, items, loading, open, query, onClose }: PreviewContextModalProps) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        aria-busy={loading}
        aria-labelledby="preview-context-title"
        aria-modal="true"
        className="memory-modal memory-modal--context"
        role="dialog"
      >
        <header className="modal-header">
          <div>
            <h2 id="preview-context-title">Preview context</h2>
            <p>{query.trim() ? `Search: ${query.trim()}` : "Full graph context"}</p>
          </div>
          <button className="icon-action" onClick={onClose} type="button" aria-label="Close context preview">
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <div className="modal-body modal-body--context">
          {error ? <p className="context-preview-error">{error}</p> : null}
          {loading ? <p className="context-preview-empty">Loading context...</p> : null}
          {!loading && !error && !items.length ? <p className="context-preview-empty">No matching context.</p> : null}
          {!loading && !error && items.length ? (
            <div className="context-preview-list">
              {items.map((item, index) => (
                <article className="context-preview-card" key={item.node_id || `${item.title}-${index}`}>
                  <header>
                    <span>{labelForType(item.type || "note")}</span>
                    {typeof item.relevance === "number" ? <small>{Math.round(item.relevance * 100)}%</small> : null}
                  </header>
                  <strong>{item.title}</strong>
                  <p>{truncate(item.summary || item.body_text, 220)}</p>
                  {item.reason ? <small>{item.reason}</small> : null}
                </article>
              ))}
            </div>
          ) : null}
        </div>

        <footer className="modal-actions">
          <button className="secondary-action" onClick={onClose} type="button">Close</button>
        </footer>
      </section>
    </div>
  );
}
