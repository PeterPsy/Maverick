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

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (!target || containerRef.current?.contains(target)) {
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
        <div className="chatapp-composer-utilities__tools">{children}</div>
      </div>
    </div>
  );
}
