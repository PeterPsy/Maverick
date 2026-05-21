export function QueuedMessageNotice({ queuedCount, queuedPreview }: { queuedCount: number; queuedPreview: string | null }) {
  if (queuedCount === 0) {
    return null;
  }
  return (
    <div className="chatapp-composer-queue" aria-live="polite">
      <div className="chatapp-composer-queue__eyebrow">
        <strong>
          {queuedCount} {queuedCount === 1 ? "message" : "messages"} queued
        </strong>
        <span>Sends automatically after the active turn</span>
      </div>
      {queuedPreview ? <div className="chatapp-composer-queue__preview">{queuedPreview}</div> : null}
    </div>
  );
}
