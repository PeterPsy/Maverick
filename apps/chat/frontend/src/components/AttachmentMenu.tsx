import { useRef } from "react";
import { canAddMoreAttachments, ComposerAttachment } from "../lib/attachments";

export function AttachmentMenu({
  attachments,
  disabled,
  onAddAttachments,
  onCapturePageArea,
}: {
  attachments: ComposerAttachment[];
  disabled: boolean;
  onAddAttachments: (files: File[]) => void;
  onCapturePageArea?: () => void;
}) {
  const attachmentMenuRef = useRef<HTMLDivElement | null>(null);
  const fileAttachmentInputRef = useRef<HTMLInputElement | null>(null);

  function addFromFileList(fileList: FileList | null) {
    const files = Array.from(fileList || []);
    if (!files.length) {
      return;
    }
    onAddAttachments(files);
  }

  return (
    <>
      <input
        ref={fileAttachmentInputRef}
        accept="image/*,text/*,application/json,application/pdf,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.csv,.json,.md,.pdf,.txt,.xls,.xlsx,.doc,.docx"
        className="chatapp-sr-only"
        multiple
        onChange={(event) => {
          addFromFileList(event.currentTarget.files);
          event.currentTarget.value = "";
        }}
        type="file"
      />
      <div ref={attachmentMenuRef} className="chat-ui-dropdown chatapp-attachment-picker">
        <button
          aria-label="Add attachments"
          className="chat-ui-dropdown__trigger chatapp-attachment-picker__trigger"
          disabled={disabled || !canAddMoreAttachments(attachments.length)}
          onClick={() => fileAttachmentInputRef.current?.click()}
          title={onCapturePageArea ? "Add files, images, or drag and drop" : "Add files or images"}
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-rounded">
            add
          </span>
        </button>
        {onCapturePageArea ? (
          <button
            aria-label="Capture page area"
            className="chat-ui-dropdown__trigger chatapp-attachment-picker__trigger chatapp-attachment-picker__capture-trigger"
            disabled={disabled}
            onClick={onCapturePageArea}
            title="Capture page area"
            type="button"
          >
            <span aria-hidden="true" className="material-symbols-rounded">
              crop_free
            </span>
          </button>
        ) : null}
      </div>
    </>
  );
}
