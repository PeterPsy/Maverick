import { useEffect } from 'react';
import { AlertTriangle, Trash2, X } from 'lucide-react';

type DeleteSkillDialogProps = {
  skillName: string;
  deleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export function DeleteSkillDialog({ skillName, deleting, onCancel, onConfirm }: DeleteSkillDialogProps) {
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
        className="maverick-modal delete-skill-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-skill-title"
        aria-describedby="delete-skill-description"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="modal-header">
          <div>
            <h2 id="delete-skill-title">Delete Skill</h2>
            <p id="delete-skill-description">Remove this runtime skill from the workspace catalog.</p>
          </div>
          <button className="icon-action" type="button" onClick={onCancel} aria-label="Close" disabled={deleting}>
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <div className="delete-skill-warning">
          <AlertTriangle size={18} aria-hidden="true" />
          <p>
            <strong>{skillName}</strong> will no longer be available to runtime sessions that use workspace skills.
          </p>
        </div>

        <footer className="modal-actions">
          <button className="secondary-action" type="button" onClick={onCancel} disabled={deleting}>
            Cancel
          </button>
          <button className="danger-action" type="button" onClick={onConfirm} disabled={deleting}>
            <Trash2 size={16} aria-hidden="true" />
            {deleting ? 'Deleting' : 'Delete Skill'}
          </button>
        </footer>
      </section>
    </div>
  );
}
