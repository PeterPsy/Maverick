import { useMemo, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import type { AppRegistryItem } from "../api";
import { clampFloatingChatWidth, type FloatingChatMode } from "../session";
import type { ShellThemeState } from "../theme";
import { WidgetSlot } from "./WidgetSlot";

type FloatingChatPlacement = "overlay" | "fixed-right" | "mobile-fullscreen";

export function FloatingChatHost({
  activeApp,
  activeWorkspaceId,
  floatingChatMode,
  isChatAppActive,
  isMobileChatClosing,
  isMobileChatOpen,
  isMobileLayout,
  navigationScope,
  onActiveThreadChange,
  onCloseDock,
  onCloseMobileChat,
  onOpenApp,
  onOpenDock,
  onResizeActiveChange,
  onWidthChange,
  shellTheme,
  threadId,
  user,
  widthPx,
}: {
  activeApp: AppRegistryItem | null;
  activeWorkspaceId: string;
  floatingChatMode: FloatingChatMode;
  isChatAppActive: boolean;
  isMobileChatClosing: boolean;
  isMobileChatOpen: boolean;
  isMobileLayout: boolean;
  navigationScope: string | null;
  onActiveThreadChange: (event: { navigationScope: string | null; threadId: string }) => void;
  onCloseDock: () => void;
  onCloseMobileChat: () => void;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  onOpenDock: (request: {
    navigationScope: string | null;
    ownerAppId: string;
    placement: "right";
    threadId: string | null;
    widgetId: string;
  }) => void;
  onResizeActiveChange?: (active: boolean) => void;
  onWidthChange: (widthPx: number) => void;
  shellTheme: ShellThemeState;
  threadId: string | null;
  user: { username?: string | null } | null;
  widthPx: number;
}) {
  const resizeDragRef = useRef<{ pointerId: number; startWidthPx: number; startX: number } | null>(null);
  const [isResizeActive, setIsResizeActive] = useState(false);
  const [resizeHandleY, setResizeHandleY] = useState("50%");
  const placement: FloatingChatPlacement = isMobileLayout
    ? "mobile-fullscreen"
    : floatingChatMode === "fixed-right"
      ? "fixed-right"
      : "overlay";
  const isDockMode = placement === "fixed-right";
  const isMobileMode = placement === "mobile-fullscreen";
  const isVisible = isMobileMode ? (isMobileChatOpen || isMobileChatClosing) && !isChatAppActive : !isChatAppActive;
  const widgetSize = isDockMode || isMobileMode ? "fill" : "overlay";
  const contentKind = isDockMode
    ? "shell.dock.right"
    : isMobileMode
      ? "shell.overlay.mobile.fullscreen"
      : "shell.overlay.bottomright";
  const widgetLabel = isDockMode ? "Right dock widget" : isMobileMode ? "Mobile chat widget" : "Floating chat widget";
  const content = useMemo(
    () => ({
      active_app: activeApp
        ? {
            app_id: activeApp.app_id,
            description: activeApp.description,
            name: activeApp.name,
            views: activeApp.views,
          }
        : null,
      mode: placement,
      navigation_scope: isDockMode ? navigationScope || "chat-floating-dock" : isMobileMode ? "chat-floating-mobile" : "",
      placement: isDockMode ? "right" : isMobileMode ? "mobile-fullscreen" : "bottom-right",
      thread_id: isDockMode ? threadId || "" : "",
      user: user?.username || null,
    }),
    [activeApp, isDockMode, isMobileMode, navigationScope, placement, threadId, user?.username],
  );

  if (!isVisible) {
    return null;
  }

  function handleCloseWidget() {
    if (isMobileMode) {
      onCloseMobileChat();
      return;
    }
    onCloseDock();
  }

  function handleResizePointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!isDockMode || event.button !== 0) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    updateResizeHandleY(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeDragRef.current = {
      pointerId: event.pointerId,
      startWidthPx: widthPx,
      startX: event.clientX,
    };
    setIsResizeActive(true);
    onResizeActiveChange?.(true);
  }

  function handleResizePointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    updateResizeHandleY(event);
    const drag = resizeDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    onWidthChange(clampFloatingChatWidth(drag.startWidthPx + drag.startX - event.clientX));
  }

  function updateResizeHandleY(event: ReactPointerEvent<HTMLButtonElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!Number.isFinite(rect.height) || rect.height <= 0) {
      return;
    }
    const edgePaddingPx = 20;
    const boundedY = Math.min(Math.max(event.clientY - rect.top, edgePaddingPx), Math.max(edgePaddingPx, rect.height - edgePaddingPx));
    setResizeHandleY(`${Math.round(boundedY)}px`);
  }

  function handleResizePointerEnd(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = resizeDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.currentTarget.hasPointerCapture === "function" && event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    resizeDragRef.current = null;
    setIsResizeActive(false);
    onResizeActiveChange?.(false);
  }

  function handleResizeKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (!isDockMode || (event.key !== "ArrowRight" && event.key !== "ArrowLeft" && event.key !== "Home")) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    if (event.key === "Home") {
      onWidthChange(clampFloatingChatWidth(null));
      return;
    }
    const direction = event.key === "ArrowLeft" ? 1 : -1;
    onWidthChange(clampFloatingChatWidth(widthPx + direction * 24));
  }

  return (
    <section
      aria-hidden={!isVisible}
      aria-label={isMobileMode ? "Chat contestuale" : isDockMode ? "Right dock panel" : "Shell overlay widgets"}
      className={`bs-floating-chat-host is-${placement} ${isVisible ? "is-visible" : ""} ${isMobileChatClosing ? "is-closing" : ""} ${isResizeActive ? "is-resizing" : ""}`}
    >
      <div className="bs-floating-chat-host__surface">
        <WidgetSlot
          activeWorkspaceId={activeWorkspaceId}
          content={content}
          contentKind={contentKind}
          hostAppId="base-shell"
          label={widgetLabel}
          onActiveThreadChange={({ navigationScope: nextNavigationScope, threadId: nextThreadId }) =>
            onActiveThreadChange({
              navigationScope: nextNavigationScope || navigationScope,
              threadId: nextThreadId,
            })
          }
          onCloseDock={handleCloseWidget}
          onOpenApp={onOpenApp}
          onOpenDock={onOpenDock}
          preferredOwnerAppId="chat"
          shellTheme={shellTheme}
          size={widgetSize}
        />
      </div>
      <button
        aria-label="Ridimensiona chat laterale"
        className="bs-floating-chat-host__resize-handle"
        disabled={!isDockMode}
        onKeyDown={handleResizeKeyDown}
        onPointerCancel={handleResizePointerEnd}
        onPointerDown={handleResizePointerDown}
        onPointerEnter={updateResizeHandleY}
        onPointerMove={handleResizePointerMove}
        onPointerUp={handleResizePointerEnd}
        style={{ "--bs-right-dock-resize-icon-y": resizeHandleY } as CSSProperties}
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">arrow_left_alt</span>
      </button>
    </section>
  );
}
