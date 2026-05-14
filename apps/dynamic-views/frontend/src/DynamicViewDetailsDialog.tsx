import { useEffect } from 'react';
import { formatDynamicViewDate, snapshotModeLabel } from './lib/dynamicViewFormatting';
import type { DynamicViewInstance } from './types';

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="dv-inspector-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function DynamicViewDetailsDialog({
  isOpen,
  onClose,
  view
}: {
  isOpen: boolean;
  onClose: () => void;
  view: DynamicViewInstance | null;
}) {
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !view) {
    return null;
  }

  const tags = view.package.tags || [];
  const dataBindings = view.data_bindings || [];

  return (
    <div className="dv-modal-backdrop" onMouseDown={onClose}>
      <section
        aria-labelledby="dynamic-view-details-title"
        aria-modal="true"
        className="dv-details-dialog dv-card-panel"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header className="dv-details-dialog-header">
          <div>
            <p className="dv-eyebrow">Details</p>
            <h2 id="dynamic-view-details-title">{view.title}</h2>
          </div>
          <button aria-label="Close details" autoFocus className="dv-icon-button" onClick={onClose} title="Close" type="button">
            <span className="material-symbols-rounded" aria-hidden="true">close</span>
          </button>
        </header>

        <div className="dv-inspector-body">
          <dl className="dv-inspector-list">
            <DetailRow label="Status" value={view.status || 'ready'} />
            <DetailRow label="Renderer" value={view.package.renderer} />
            <DetailRow label="Snapshot mode" value={snapshotModeLabel(view.snapshot_mode)} />
            <DetailRow label="Created" value={formatDynamicViewDate(view.created_at)} />
            <DetailRow label="Updated" value={formatDynamicViewDate(view.updated_at)} />
            <DetailRow label="Instance ID" value={view.id} />
          </dl>

          <section className="dv-inspector-section" aria-label="Tags">
            <h3>Tags</h3>
            {tags.length ? (
              <div className="dv-tag-list">
                {tags.map((tag, index) => <span className="dv-tag" key={`${tag}:${index}`}>{tag}</span>)}
              </div>
            ) : (
              <p>No tags.</p>
            )}
          </section>

          <section className="dv-inspector-section" aria-label="Data sources">
            <h3>Sources</h3>
            {dataBindings.length ? (
              <ul className="dv-source-list">
                {dataBindings.map((binding, index) => (
                  <li key={`${binding.source_type}:${binding.source_ref}:${index}`}>
                    <strong>{binding.source_type}</strong>
                    <span>{binding.source_ref}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No source bindings.</p>
            )}
          </section>
        </div>
      </section>
    </div>
  );
}
