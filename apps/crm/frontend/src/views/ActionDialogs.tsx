import { FormEvent, useEffect, useState } from 'react';
import { Save, Tag, X } from 'lucide-react';
import { ActionDialogState } from '../domain/types';

export type ActionDialogValues = {
  title?: string;
  tag?: string;
  name?: string;
  probability?: number;
};

export function ActionDialog({
  dialog,
  isSaving,
  onClose,
  onSubmit
}: {
  dialog: ActionDialogState;
  isSaving: boolean;
  onClose: () => void;
  onSubmit: (values: ActionDialogValues) => Promise<boolean>;
}) {
  const [title, setTitle] = useState('');
  const [tag, setTag] = useState('');
  const [name, setName] = useState('');
  const [probability, setProbability] = useState('0.5');

  useEffect(() => {
    setTitle('');
    setTag('');
    setName(dialog?.kind === 'pipeline-stage' ? dialog.stage?.name || '' : '');
    setProbability(dialog?.kind === 'pipeline-stage' ? String(dialog.stage?.probability ?? 0.5) : '0.5');
  }, [dialog]);

  if (!dialog) return null;

  const copy = actionDialogCopy(dialog);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ok = await onSubmit({
      title: title.trim(),
      tag: tag.trim(),
      name: name.trim(),
      probability: Number(probability)
    });
    if (ok) onClose();
  }

  return (
    <div className="crm-detail-overlay" onMouseDown={onClose}>
      <section className="crm-detail-dialog crm-action-dialog" role="dialog" aria-modal="true" aria-labelledby="crm-action-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="detail-header">
          <div>
            <small>{copy.eyebrow}</small>
            <h2 id="crm-action-dialog-title">{copy.title}</h2>
          </div>
          <button className="detail-close" type="button" onClick={onClose} aria-label="Close action dialog">
            <X size={16} aria-hidden="true" />
          </button>
        </header>
        <form className="composer-form" onSubmit={handleSubmit}>
          {dialog.kind === 'save-view' ? (
            <label>
              View name
              <input autoFocus required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Hot accounts" />
            </label>
          ) : null}
          {dialog.kind === 'record-tag' || dialog.kind === 'bulk-tag' ? (
            <label>
              Tag
              <input autoFocus required value={tag} onChange={(event) => setTag(event.target.value)} placeholder="enterprise" />
            </label>
          ) : null}
          {dialog.kind === 'pipeline-stage' ? (
            <div className="composer-grid">
              <label>
                Stage name
                <input autoFocus required value={name} onChange={(event) => setName(event.target.value)} placeholder="Negotiation" />
              </label>
              <label>
                Probability
                <input required type="number" min="0" max="1" step="0.01" value={probability} onChange={(event) => setProbability(event.target.value)} />
              </label>
            </div>
          ) : null}
          <div className="composer-actions">
            <button type="button" onClick={onClose} disabled={isSaving}>Cancel</button>
            <button type="submit" disabled={isSaving}>
              {dialog.kind === 'record-tag' || dialog.kind === 'bulk-tag' ? <Tag size={15} aria-hidden="true" /> : <Save size={15} aria-hidden="true" />}
              <span>{copy.submit}</span>
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function actionDialogCopy(dialog: NonNullable<ActionDialogState>) {
  if (dialog.kind === 'save-view') {
    return { eyebrow: 'Saved view', title: 'Save current view', submit: 'Save view' };
  }
  if (dialog.kind === 'record-tag') {
    return { eyebrow: 'Record tag', title: 'Tag record', submit: 'Apply tag' };
  }
  if (dialog.kind === 'bulk-tag') {
    return { eyebrow: 'Bulk action', title: 'Tag selected records', submit: 'Apply tag' };
  }
  return {
    eyebrow: 'Pipeline',
    title: dialog.stage ? 'Edit pipeline stage' : 'Add pipeline stage',
    submit: dialog.stage ? 'Save stage' : 'Add stage'
  };
}
