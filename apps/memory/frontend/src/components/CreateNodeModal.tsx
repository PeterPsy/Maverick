import { X } from "lucide-react";
import { nodeTypes } from "../constants";
import { labelForType } from "../format";
import type { NodeDraft } from "../types";

type CreateNodeModalProps = {
  draft: NodeDraft;
  open: boolean;
  saving: boolean;
  onClose: () => void;
  onCreate: () => void;
  onDraftChange: (draft: NodeDraft) => void;
};

export function CreateNodeModal({ draft, open, saving, onClose, onCreate, onDraftChange }: CreateNodeModalProps) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="memory-modal" aria-labelledby="create-node-title" role="dialog" aria-modal="true">
        <header className="modal-header">
          <div>
            <h2 id="create-node-title">Create node</h2>
            <p>Save a durable memory item in the workspace graph.</p>
          </div>
          <button className="icon-action" onClick={onClose} type="button" aria-label="Close create node modal" disabled={saving}>
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <div className="modal-body">
          <label>
            Title
            <input
              autoFocus
              value={draft.title}
              onChange={(event) => onDraftChange({ ...draft, title: event.target.value })}
              placeholder="Decision, fact, person, or topic"
            />
          </label>
          <label>
            Type
            <select value={draft.type} onChange={(event) => onDraftChange({ ...draft, type: event.target.value })}>
              {nodeTypes.map((type) => <option key={type} value={type}>{labelForType(type)}</option>)}
            </select>
          </label>
          <label>
            Content
            <textarea
              value={draft.body}
              onChange={(event) => onDraftChange({ ...draft, body: event.target.value })}
              placeholder="Durable note, fact, decision, or context"
            />
          </label>
        </div>

        <footer className="modal-actions">
          <button className="secondary-action" onClick={onClose} type="button" disabled={saving}>Cancel</button>
          <button className="primary-action" onClick={onCreate} type="button" disabled={saving || !draft.title.trim()}>
            {saving ? "Creating..." : "Create"}
          </button>
        </footer>
      </section>
    </div>
  );
}
