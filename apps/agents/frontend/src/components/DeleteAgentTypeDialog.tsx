import { useEffect } from 'react';
import { AlertTriangle, Trash2, X } from 'lucide-react';

type DeleteAgentTypeDialogProps = {
  agentName: string;
  deleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export function DeleteAgentTypeDialog({ agentName, deleting, onCancel, onConfirm }: DeleteAgentTypeDialogProps) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !deleting) {
        onCancel();
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [deleting, onCancel]);

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={() => !deleting && onCancel()}>
      <section
        className="agent-modal delete-agent-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-agent-title"
        aria-describedby="delete-agent-description"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="modal-header">
          <div>
            <h2 id="delete-agent-title">Delete Agent</h2>
            <p id="delete-agent-description">Remove this agent type from the workspace catalog.</p>
          </div>
          <button className="icon-action" type="button" onClick={onCancel} aria-label="Close" disabled={deleting}>
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <div className="delete-agent-warning">
          <AlertTriangle size={18} aria-hidden="true" />
          <p>
            <strong>{agentName}</strong> will no longer be available for new runtime sessions.
          </p>
        </div>

        <footer className="modal-actions">
          <button className="secondary-action" type="button" onClick={onCancel} disabled={deleting}>
            Cancel
          </button>
          <button className="danger-action" type="button" onClick={onConfirm} disabled={deleting}>
            <Trash2 size={16} aria-hidden="true" />
            {deleting ? 'Deleting' : 'Delete Agent'}
          </button>
        </footer>
      </section>
    </div>
  );
}
