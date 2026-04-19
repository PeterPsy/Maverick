import { CSSProperties, useEffect, useLayoutEffect, useRef, useState } from "react";
import { canAddMoreAttachments, ComposerAttachment } from "../lib/attachments";

export function AttachmentMenu({
  attachments,
  disabled,
  onAddAttachments,
}: {
  attachments: ComposerAttachment[];
  disabled: boolean;
  onAddAttachments: (files: File[]) => void;
}) {
  const attachmentMenuRef = useRef<HTMLDivElement | null>(null);
  const attachmentMenuPanelRef = useRef<HTMLDivElement | null>(null);
  const imageAttachmentInputRef = useRef<HTMLInputElement | null>(null);
  const fileAttachmentInputRef = useRef<HTMLInputElement | null>(null);
  const [isAttachmentMenuOpen, setIsAttachmentMenuOpen] = useState(false);
  const [attachmentMenuStyle, setAttachmentMenuStyle] = useState<CSSProperties | null>(null);

  function addFromFileList(fileList: FileList | null) {
    const files = Array.from(fileList || []);
    if (!files.length) {
      return;
    }
    onAddAttachments(files);
    setIsAttachmentMenuOpen(false);
  }

  useLayoutEffect(() => {
    if (!isAttachmentMenuOpen) {
      setAttachmentMenuStyle(null);
      return;
    }

    const updateAttachmentMenuPosition = () => {
      const rootElement = attachmentMenuRef.current;
      const menuElement = attachmentMenuPanelRef.current;
      if (!rootElement || !menuElement) {
        return;
      }
      const triggerRect = rootElement.getBoundingClientRect();
      const viewport = window.visualViewport;
      const viewportWidth = viewport?.width ?? window.innerWidth;
      const viewportHeight = viewport?.height ?? window.innerHeight;
      const viewportOffsetLeft = viewport?.offsetLeft ?? 0;
      const viewportOffsetTop = viewport?.offsetTop ?? 0;
      const gap = 12;
      const menuWidth = menuElement.offsetWidth || 220;
      const menuHeight = menuElement.offsetHeight || 0;
      const left = Math.max(viewportOffsetLeft + gap, Math.min(triggerRect.left + viewportOffsetLeft, viewportOffsetLeft + viewportWidth - menuWidth - gap));
      const spaceBelow = viewportOffsetTop + viewportHeight - triggerRect.bottom - gap;
      const spaceAbove = triggerRect.top - viewportOffsetTop - gap;
      const openAbove = spaceBelow < menuHeight && spaceAbove > spaceBelow;
      const availableHeight = Math.max(120, openAbove ? spaceAbove : spaceBelow);
      const constrainedHeight = Math.min(menuHeight, availableHeight);
      const top = openAbove
        ? Math.max(viewportOffsetTop + gap, triggerRect.top + viewportOffsetTop - constrainedHeight - gap)
        : Math.min(triggerRect.bottom + viewportOffsetTop + gap, viewportOffsetTop + viewportHeight - constrainedHeight - gap);
      setAttachmentMenuStyle({ left, maxHeight: availableHeight, top, visibility: "visible" });
    };

    updateAttachmentMenuPosition();
    window.addEventListener("resize", updateAttachmentMenuPosition);
    window.addEventListener("scroll", updateAttachmentMenuPosition, true);
    window.visualViewport?.addEventListener("resize", updateAttachmentMenuPosition);
    window.visualViewport?.addEventListener("scroll", updateAttachmentMenuPosition);
    return () => {
      window.removeEventListener("resize", updateAttachmentMenuPosition);
      window.removeEventListener("scroll", updateAttachmentMenuPosition, true);
      window.visualViewport?.removeEventListener("resize", updateAttachmentMenuPosition);
      window.visualViewport?.removeEventListener("scroll", updateAttachmentMenuPosition);
    };
  }, [isAttachmentMenuOpen]);

  useEffect(() => {
    if (!isAttachmentMenuOpen) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target || attachmentMenuRef.current?.contains(target) || attachmentMenuPanelRef.current?.contains(target)) {
        return;
      }
      setIsAttachmentMenuOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsAttachmentMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isAttachmentMenuOpen]);

  return (
    <>
      <input
        ref={imageAttachmentInputRef}
        accept="image/*"
        className="chatapp-sr-only"
        multiple
        onChange={(event) => {
          addFromFileList(event.currentTarget.files);
          event.currentTarget.value = "";
        }}
        type="file"
      />
      <input
        ref={fileAttachmentInputRef}
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
          aria-expanded={isAttachmentMenuOpen}
          aria-haspopup="menu"
          aria-label="Aggiungi allegati"
          className="chat-ui-dropdown__trigger chatapp-attachment-picker__trigger"
          disabled={disabled || !canAddMoreAttachments(attachments.length)}
          onClick={() => setIsAttachmentMenuOpen((current) => !current)}
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-rounded">
            add
          </span>
        </button>
        {isAttachmentMenuOpen ? (
          <div className="chat-ui-dropdown__menu chat-ui-dropdown__menu--left chatapp-attachment-picker__menu" ref={attachmentMenuPanelRef} role="menu" style={attachmentMenuStyle ?? { visibility: "hidden" }}>
            <AttachmentMenuItem icon="image" iconClass="chatapp-attachment-picker__item-icon--image" onClick={() => imageAttachmentInputRef.current?.click()} title="Carica immagine" detail="Screenshot, foto e altri file visivi" />
            <AttachmentMenuItem icon="description" iconClass="chatapp-attachment-picker__item-icon--file" onClick={() => fileAttachmentInputRef.current?.click()} title="Carica file" detail="PDF, testo, fogli di calcolo e documenti" />
          </div>
        ) : null}
      </div>
    </>
  );
}

function AttachmentMenuItem({ detail, icon, iconClass, onClick, title }: { detail: string; icon: string; iconClass: string; onClick: () => void; title: string }) {
  return (
    <button className="chat-ui-dropdown__item chatapp-attachment-picker__item" onClick={onClick} role="menuitem" type="button">
      <span aria-hidden="true" className={`chatapp-attachment-picker__item-icon ${iconClass}`}>
        <span className="material-symbols-rounded">{icon}</span>
      </span>
      <span className="chatapp-attachment-picker__item-copy">
        <span className="chatapp-attachment-picker__item-title">{title}</span>
        <span className="chatapp-attachment-picker__item-detail">{detail}</span>
      </span>
    </button>
  );
}
