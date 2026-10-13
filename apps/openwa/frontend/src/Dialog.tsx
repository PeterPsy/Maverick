import { useEffect, useRef, type ReactNode } from "react";

export function Dialog({ label, onClose, children }: {
  label: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const root = panel.current;
    const focusable = () => Array.from(root?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex="0"]',
    ) || []).filter((node) => node.getClientRects().length > 0);
    (focusable()[0] || root)?.focus();
    function key(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
      } else if (event.key === "Tab") {
        const nodes = focusable();
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (!first) {
          event.preventDefault();
          root?.focus();
        } else if (event.shiftKey && (document.activeElement === first || document.activeElement === root)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, []);
  return <div className="modal-backdrop" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <div ref={panel} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}>
      {children}
    </div>
  </div>;
}
