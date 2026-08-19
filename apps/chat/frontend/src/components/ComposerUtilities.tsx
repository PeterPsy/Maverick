import {
  useEffect,
  useId,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

export function ComposerUtilities({ actions, children }: { actions: ReactNode; children: ReactNode }) {
  const panelId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  function keepTriggerStable(event: ReactPointerEvent<HTMLButtonElement>) {
    // Retain editor focus so the expanded mobile composer cannot collapse before the tap completes.
    event.preventDefault();
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
      setIsOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") {
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

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <div className="chatapp-composer-utilities" ref={containerRef}>
      <button
        aria-controls={panelId}
        aria-expanded={isOpen}
        aria-label="Composer utilities"
        className={`chatapp-composer__tool-button chatapp-composer-utilities__trigger ${isOpen ? "is-active" : ""}`}
        onClick={() => setIsOpen((current) => !current)}
        onPointerDown={keepTriggerStable}
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
        {actions}
      </div>
    </div>
  );
}
