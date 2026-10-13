import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";

export function ComposerUtilities({ children, externalPanelOpen = false }: { children: ReactNode; externalPanelOpen?: boolean }) {
  const panelId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  function nestedTrigger() {
    return containerRef.current?.querySelector<HTMLButtonElement>(
      '[aria-expanded="true"]:not(.chatapp-composer-utilities__trigger)',
    );
  }

  function returnToUtilities() {
    const trigger = nestedTrigger();
    trigger?.click();
    window.requestAnimationFrame(() => trigger?.focus({ preventScroll: true }));
  }

  function closePanel() {
    nestedTrigger()?.click();
    setIsOpen(false);
    triggerRef.current?.focus({ preventScroll: true });
  }

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (!target || containerRef.current?.contains(target)) {
        return;
      }
      const dialogTrigger = containerRef.current?.querySelector('[aria-haspopup="dialog"][aria-expanded="true"]');
      const dialogId = dialogTrigger?.getAttribute("aria-controls");
      const dialogBackdrop = dialogId ? document.getElementById(dialogId)?.closest(".chatapp-usage-modal-backdrop") : null;
      if (dialogBackdrop?.contains(target)) {
        return;
      }
      const composer = containerRef.current?.closest(".chatapp-composer");
      if (externalPanelOpen && composer?.querySelector(".chatapp-mention-panel--app-picker")?.contains(target)) {
        return;
      }
      setIsOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented || externalPanelOpen) {
        return;
      }
      const nestedPopupTrigger = containerRef.current?.querySelector<HTMLElement>(
        '[aria-expanded="true"]:not(.chatapp-composer-utilities__trigger)',
      );
      if (nestedPopupTrigger) {
        return;
      }
      setIsOpen(false);
      triggerRef.current?.focus();
    }

    // Inspect containment before an option's handler removes its popup.
    document.addEventListener("pointerdown", handlePointerDown, true);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [externalPanelOpen, isOpen]);

  return (
    <div className="chatapp-composer-utilities" ref={containerRef}>
      <button
        aria-controls={panelId}
        aria-expanded={isOpen}
        aria-label="Composer utilities"
        className={`chatapp-composer__tool-button chatapp-composer-utilities__trigger ${isOpen ? "is-active" : ""}`}
        onClick={() => setIsOpen((current) => !current)}
        ref={triggerRef}
        title="Composer utilities"
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">
          construction
        </span>
      </button>
      <div
        aria-label="Composer utility controls"
        className={`chatapp-composer-utilities__menu ${isOpen ? "is-open" : ""}`}
        id={panelId}
        role="group"
      >
        <div
          className="chatapp-composer-utilities__header"
          onPointerDown={(event) => event.stopPropagation()}
          onKeyDown={(event) => {
            if (event.key === "Escape" && nestedTrigger()) {
              event.preventDefault();
              event.stopPropagation();
              returnToUtilities();
            }
          }}
        >
          <button
            aria-label="Back to utilities"
            className="chatapp-composer-utilities__back"
            onClick={returnToUtilities}
            type="button"
          >
            <span aria-hidden="true" className="material-symbols-rounded">arrow_back</span>
          </button>
          <span className="chatapp-composer-utilities__title">Chat utilities</span>
          <button
            aria-label="Close utilities"
            className="chatapp-composer-utilities__close"
            onClick={closePanel}
            type="button"
          >
            <span aria-hidden="true" className="material-symbols-rounded">close</span>
          </button>
        </div>
        <div className="chatapp-composer-utilities__tools">{children}</div>
      </div>
    </div>
  );
}
