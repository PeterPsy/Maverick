import { DragEvent, FormEvent, useEffect, useState } from "react";
import type { ComposerAttachment } from "../lib/attachments";
import { hasInvalidAttachments } from "../lib/attachments";
import { AttachmentMenu } from "./AttachmentMenu";
import { AttachmentPreviewStrip } from "./AttachmentPreviewStrip";

export function ChatComposer({
  attachments,
  canStopTurn,
  disabled,
  error,
  isSending,
  onAddAttachments,
  onChange,
  onRemoveAttachment,
  onStopTurn,
  onSubmit,
  queuedCount,
  queuedPreview,
  value,
}: {
  attachments: ComposerAttachment[];
  canStopTurn: boolean;
  disabled: boolean;
  error: string | null;
  isSending: boolean;
  onAddAttachments: (files: File[]) => void;
  onChange: (value: string) => void;
  onRemoveAttachment: (attachmentId: string) => void;
  onStopTurn: () => void;
  onSubmit: () => void;
  queuedCount: number;
  queuedPreview: string | null;
  value: string;
}) {
  const [isDraggingFiles, setIsDraggingFiles] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }

  function onDragOver(event: DragEvent<HTMLTextAreaElement>) {
    if (!event.dataTransfer.types.includes("Files")) {
      return;
    }
    event.preventDefault();
    setIsDraggingFiles(true);
  }

  function onDrop(event: DragEvent<HTMLTextAreaElement>) {
    if (!event.dataTransfer.files.length) {
      return;
    }
    event.preventDefault();
    setIsDraggingFiles(false);
    onAddAttachments(Array.from(event.dataTransfer.files));
  }

  useEffect(() => {
    const handlePaste = (event: ClipboardEvent) => {
      if (disabled || !event.clipboardData?.files.length) {
        return;
      }
      onAddAttachments(Array.from(event.clipboardData.files));
    };
    document.addEventListener("paste", handlePaste);
    return () => document.removeEventListener("paste", handlePaste);
  }, [disabled, onAddAttachments]);

  return (
    <section className="chat-ui-surface chatapp-composer">
      {isDraggingFiles ? <DropOverlay /> : null}
      <form className="chatapp-form-stack" onSubmit={submit}>
        <AttachmentPreviewStrip attachments={attachments} disabled={isSending} onRemoveAttachment={onRemoveAttachment} />
        <QueuedMessageNotice queuedCount={queuedCount} queuedPreview={queuedPreview} />
        <div className={`chatapp-composer__row ${isSending ? "is-busy" : "is-idle"}`}>
          <AttachmentMenu attachments={attachments} disabled={disabled} onAddAttachments={onAddAttachments} />
          <textarea
            className="chat-ui-input chat-ui-input--textarea chatapp-composer__field"
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            onDragLeave={() => setIsDraggingFiles(false)}
            onDragOver={onDragOver}
            onDrop={onDrop}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.altKey) {
                event.preventDefault();
                onSubmit();
              }
            }}
            placeholder="Fai una domanda"
            rows={3}
            value={value}
          />
          <ComposerActions
            canSend={!disabled && !hasInvalidAttachments(attachments) && Boolean(value.trim() || attachments.length)}
            canStopTurn={canStopTurn}
            isSending={isSending}
            onStopTurn={onStopTurn}
          />
        </div>
        {error ? <div className="chat-ui-field__message chat-ui-field__message--error chatapp-composer__error">{error}</div> : null}
        <div className={`chatapp-composer__status ${isSending ? "" : "is-connected"}`} aria-live="polite">
          {isSending ? "Runtime working" : "Runtime connected"}
        </div>
      </form>
    </section>
  );
}

function ComposerActions({
  canSend,
  canStopTurn,
  isSending,
  onStopTurn,
}: {
  canSend: boolean;
  canStopTurn: boolean;
  isSending: boolean;
  onStopTurn: () => void;
}) {
  return (
    <div className="chatapp-composer__actions">
      {canStopTurn ? (
        <button aria-label="Stop turn" className="chatapp-composer__icon-action is-stop" onClick={onStopTurn} title="Stop" type="button">
          <span aria-hidden="true" className="material-symbols-rounded">
            stop
          </span>
        </button>
      ) : null}
      <button aria-label="Send message" className="chatapp-composer__icon-action is-send" disabled={!canSend || isSending} title="Send" type="submit">
        {isSending ? (
          <span className="chat-ui-button__spinner" />
        ) : (
          <span aria-hidden="true" className="material-symbols-rounded">
            send
          </span>
        )}
      </button>
    </div>
  );
}

function DropOverlay() {
  return (
    <div className="chatapp-chat-dropzone" aria-hidden="true">
      <div className="chatapp-chat-dropzone__panel">
        <span className="chatapp-chat-dropzone__eyebrow">Attachment</span>
        <strong>Rilascia qui i file</strong>
        <span>Li prepariamo nella composer prima dell'invio.</span>
      </div>
    </div>
  );
}

function QueuedMessageNotice({ queuedCount, queuedPreview }: { queuedCount: number; queuedPreview: string | null }) {
  if (queuedCount === 0) {
    return null;
  }
  return (
    <div className="chatapp-composer-queue" aria-live="polite">
      <div className="chatapp-composer-queue__eyebrow">
        <strong>{queuedCount} messaggi in coda</strong>
        <span>Invio automatico dopo il turn attivo</span>
      </div>
      {queuedPreview ? <div className="chatapp-composer-queue__preview">{queuedPreview}</div> : null}
    </div>
  );
}
