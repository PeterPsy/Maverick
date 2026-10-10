import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** Native top-layer placement keeps the inbox outside sidebar clipping. */
export function NotificationPopover({ children, toggleContent, announcement, placement }: {
  children: (close: () => void) => ReactNode;
  toggleContent: ReactNode;
  announcement: string;
  placement: "sidebar" | "header";
}) {
  const id = useId();
  const [expanded, setExpanded] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const inboxRef = useRef<HTMLElement>(null);
  const [position, setPosition] = useState({ left: 12, top: 12 });

  useLayoutEffect(() => {
    const inbox = inboxRef.current;
    if (!inbox?.isConnected) return;
    if (!expanded) {
      inbox.hidePopover();
      return;
    }
    function positionInbox() {
      const rect = toggleRef.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(340, window.innerWidth - 24);
      setPosition({
        left: Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)),
        top: Math.max(12, Math.min(rect.bottom + 8, window.innerHeight - 80)),
      });
    }
    positionInbox();
    inbox.showPopover();
    // Clicks inside isolated app frames do not reach the parent document's
    // native light-dismiss handler. Moving focus into a frame closes the inbox.
    let blurTimer = 0;
    function handleFrameFocus() {
      window.clearTimeout(blurTimer);
      blurTimer = window.setTimeout(() => {
        if (document.activeElement instanceof HTMLIFrameElement) setExpanded(false);
      }, 0);
    }
    window.addEventListener("blur", handleFrameFocus);
    window.addEventListener("resize", positionInbox);
    window.addEventListener("scroll", positionInbox, true);
    window.visualViewport?.addEventListener("resize", positionInbox);
    return () => {
      window.clearTimeout(blurTimer);
      window.removeEventListener("blur", handleFrameFocus);
      window.removeEventListener("resize", positionInbox);
      window.removeEventListener("scroll", positionInbox, true);
      window.visualViewport?.removeEventListener("resize", positionInbox);
    };
  }, [expanded]);

  return (
    <aside className="bs-notifications" aria-label="Notifiche delle app"
      onKeyDown={(event) => {
        if (event.key === "Escape" && expanded) {
          event.preventDefault();
          event.stopPropagation();
          setExpanded(false);
          toggleRef.current?.focus();
        }
      }}>
      <button type="button" ref={toggleRef} title="Notifiche"
        className={`bs-notifications__toggle ${placement === "header" ? "bs-mobile-shell-header__button" : "bs-sidebar__app-settings"}`}
        aria-expanded={expanded} aria-controls={id} popoverTarget={id}
        onClick={(event) => { event.preventDefault(); setExpanded(!expanded); }}>
        {toggleContent}
      </button>
      <span className="bs-notifications__announcement" role="status" aria-live="polite">{announcement}</span>
      <section id={id} ref={inboxRef} popover="auto" className="bs-notifications__inbox"
        aria-label="Notifiche da leggere"
        onToggle={(event) => setExpanded(event.newState === "open")}
        style={{ left: position.left, top: position.top, maxHeight: `min(560px, calc(100dvh - ${position.top + 12}px))` }}>
        {expanded ? children(() => setExpanded(false)) : null}
      </section>
    </aside>
  );
}
