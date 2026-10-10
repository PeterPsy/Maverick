import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";

export function SidebarRailMenu({ children, icon, label, placement, open, onOpenChange }: {
  children: ReactNode;
  icon: string;
  label: string;
  placement: "top" | "bottom" | "mobile";
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const expanded = open ?? isOpen;
  const id = useId();
  const groupRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const skipFocusOpen = useRef(false);

  function changeOpen(next: boolean) {
    setIsOpen(next);
    onOpenChange?.(next);
  }

  useEffect(() => {
    if (!expanded) return;
    function handleOutside(event: PointerEvent) {
      if (event.target instanceof Node && !groupRef.current?.contains(event.target)
        && !(event.target instanceof Element && event.target.closest(".bs-mobile-shell-header__menu"))) {
        changeOpen(false);
      }
    }
    document.addEventListener("pointerdown", handleOutside);
    return () => document.removeEventListener("pointerdown", handleOutside);
  }, [expanded, onOpenChange]);

  return (
    <div className={`bs-sidebar__rail-menu bs-sidebar__rail-menu--${placement}`} ref={groupRef}
      onPointerEnter={(event) => { if (placement !== "mobile" && event.pointerType !== "touch") changeOpen(true); }}
      onMouseLeave={() => { if (placement !== "mobile" && !groupRef.current?.contains(document.activeElement)) changeOpen(false); }}
      onFocus={() => {
        if (skipFocusOpen.current) { skipFocusOpen.current = false; return; }
        if (placement !== "mobile") changeOpen(true);
      }}
      onBlur={(event) => {
        if (placement === "mobile" && event.relatedTarget instanceof Element && event.relatedTarget.closest(".bs-mobile-shell-header__menu")) return;
        if (!event.currentTarget.contains(event.relatedTarget)) changeOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !expanded) return;
        event.preventDefault();
        event.stopPropagation();
        changeOpen(false);
        if (triggerRef.current && document.activeElement !== triggerRef.current) {
          skipFocusOpen.current = true;
          triggerRef.current.focus();
        }
      }}>
      {placement !== "mobile" ? <button aria-label={label} aria-expanded={expanded} aria-controls={id}
        className="bs-sidebar__rail-button bs-sidebar__rail-menu-trigger" onClick={() => changeOpen(!expanded)}
        onPointerDown={() => { if (document.activeElement !== triggerRef.current) skipFocusOpen.current = true; }}
        ref={triggerRef} type="button">
        <span aria-hidden="true" className="material-symbols-rounded">{icon}</span>
      </button> : null}
      {expanded ? <div aria-label={label} className="bs-sidebar__rail-menu-panel" id={id} role="group">{children}</div> : null}
    </div>
  );
}
