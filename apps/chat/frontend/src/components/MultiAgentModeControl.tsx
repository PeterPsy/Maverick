import { useEffect, useRef } from "react";
import type { MultiAgentComposerMode } from "../api/client";
import { usePopupFocusReturn } from "../hooks/usePopupFocusReturn";

export function MultiAgentModeControl({
  budgetLabel,
  disabled,
  groupChatEnabled,
  menuOpen,
  mode,
  onMenuOpenChange,
  onSelect,
}: {
  budgetLabel: string;
  disabled: boolean;
  groupChatEnabled: boolean;
  menuOpen: boolean;
  mode: MultiAgentComposerMode;
  onMenuOpenChange: (open: boolean) => void;
  onSelect: (mode: MultiAgentComposerMode) => void;
}) {
  const label = multiAgentModeLabel(mode);
  const modeItems: MultiAgentComposerMode[] = groupChatEnabled ? ["off", "auto", "multi", "group_chat"] : ["off", "auto", "multi"];
  const controlRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const returnFocus = usePopupFocusReturn(menuOpen, triggerRef);

  useEffect(() => {
    if (menuOpen) {
      menuRef.current?.focus({ preventScroll: true });
    }
  }, [menuOpen]);

  useEffect(() => {
    if (!menuOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (!target || controlRef.current?.contains(target)) {
        return;
      }
      onMenuOpenChange(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [menuOpen, onMenuOpenChange]);

  return (
    <div className="chatapp-multi-agent-control" ref={controlRef}>
      <button
        aria-expanded={menuOpen}
        aria-haspopup="menu"
        aria-label={`Multi-agent mode: ${label}`}
        className={`chatapp-composer__tool-button chatapp-multi-agent-control__button ${mode !== "off" ? "is-active" : ""}`}
        disabled={disabled}
        onClick={() => onMenuOpenChange(!menuOpen)}
        ref={triggerRef}
        title="Multi-agent mode"
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">
          account_tree
        </span>
        <span className="chatapp-multi-agent-control__label">{label}</span>
      </button>
      {menuOpen ? (
        <div
          className="chatapp-multi-agent-menu"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              returnFocus();
              onMenuOpenChange(false);
            }
          }}
          ref={menuRef}
          role="menu"
          tabIndex={-1}
        >
          {modeItems.map((item) => (
            <button
              aria-checked={mode === item}
              className="chatapp-multi-agent-menu__item"
              key={item}
              onClick={() => {
                returnFocus();
                onSelect(item);
              }}
              role="menuitemradio"
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                {mode === item ? "radio_button_checked" : "radio_button_unchecked"}
              </span>
              <span>{multiAgentModeLabel(item)}</span>
            </button>
          ))}
          {budgetLabel ? <div className="chatapp-multi-agent-menu__budget">{budgetLabel}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function multiAgentModeLabel(mode: MultiAgentComposerMode): string {
  if (mode === "auto") {
    return "Auto";
  }
  if (mode === "multi") {
    return "Multi";
  }
  if (mode === "group_chat") {
    return "Group chat";
  }
  return "Off";
}
