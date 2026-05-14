import type { ComposerAttachment } from "../lib/attachments";
import { formatFileSize } from "../lib/attachments";

export function AttachmentPreviewStrip({
  attachments,
  disabled,
  onRemoveAttachment,
}: {
  attachments: ComposerAttachment[];
  disabled: boolean;
  onRemoveAttachment: (attachmentId: string) => void;
}) {
  if (!attachments.length) {
    return null;
  }

  return (
    <div className="chatapp-attachment-strip" aria-label="Selected attachments">
      {attachments.map((attachment) => (
        <div
          className={`chatapp-attachment-card ${attachment.isImage ? "is-image" : ""} ${attachment.warning ? "is-invalid" : ""}`}
          key={attachment.id}
        >
          {attachment.objectUrl ? (
            <img alt="" className="chatapp-attachment-card__preview" src={attachment.objectUrl} />
          ) : (
            <span className="chatapp-attachment-card__icon" aria-hidden="true">
              <span className="material-symbols-rounded">description</span>
            </span>
          )}
          <span className="chatapp-attachment-card__meta">
            <span className="chatapp-attachment-card__name">{attachment.name}</span>
            <span className="chatapp-attachment-card__detail">{formatFileSize(attachment.size)}</span>
            {attachment.warning ? <span className="chatapp-attachment-card__warning">{attachment.warning}</span> : null}
          </span>
          <button
            aria-label={`Remove ${attachment.name}`}
            className="chatapp-attachment-card__remove"
            disabled={disabled}
            onClick={() => onRemoveAttachment(attachment.id)}
            type="button"
          >
            <span aria-hidden="true" className="material-symbols-rounded">
              close
            </span>
          </button>
        </div>
      ))}
    </div>
  );
}
