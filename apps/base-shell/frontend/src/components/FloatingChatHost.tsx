import { useEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import type { AppRegistryItem } from "../api";
import type { MaverickFrameScope } from "../iframePolicy";
import { clampFloatingChatWidth, type FloatingChatMode } from "../session";
import type { ShellThemeState } from "../theme";
import { FloatingChatWidget, type FloatingChatPlacement } from "./FloatingChatWidget";

export function FloatingChatHost({
  activeApp,
  activeAppParams = {},
  activeWorkspaceId,
  frameScope,
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
  activeAppParams?: Record<string, string | boolean | null>;
  activeWorkspaceId: string;
  frameScope: MaverickFrameScope;
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
  const scope = `${frameScope.sessionGeneration}:${activeWorkspaceId}`;
  const [mounted, setMounted] = useState<{ scope: string; placements: FloatingChatPlacement[] }>(() => ({
    scope, placements: isVisible ? [placement] : [],
  }));
  const scopedPlacements = mounted.scope === scope ? mounted.placements : [];
  const renderedPlacements = isVisible && !scopedPlacements.includes(placement)
    ? [...scopedPlacements, placement] : scopedPlacements;
  useEffect(() => {
    setMounted((current) => {
      const placements = current.scope === scope ? current.placements : [];
      if (current.scope === scope && (!isVisible || placements.includes(placement))) return current;
      return { scope, placements: isVisible && !placements.includes(placement) ? [...placements, placement] : placements };
    });
  }, [scope, isVisible, placement]);

  if (!renderedPlacements.length) return null;

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
      inert={!isVisible}
      aria-label={isMobileMode ? "Chat contestuale" : isDockMode ? "Right dock panel" : "Shell overlay widgets"}
      className={`bs-floating-chat-host is-${placement} ${isVisible ? "is-visible" : ""} ${isMobileChatClosing ? "is-closing" : ""} ${isResizeActive ? "is-resizing" : ""}`}
    >
      <div className="bs-floating-chat-host__surface">
        {renderedPlacements.map((openedPlacement) => <FloatingChatWidget
          key={`${scope}:${openedPlacement}`}
          placement={openedPlacement}
          visible={isVisible && openedPlacement === placement}
          activeApp={activeApp}
          activeAppParams={activeAppParams}
          activeWorkspaceId={activeWorkspaceId}
          frameScope={frameScope}
          navigationScope={navigationScope}
          onActiveThreadChange={onActiveThreadChange}
          onCloseDock={onCloseDock}
          onCloseMobileChat={onCloseMobileChat}
          onOpenApp={onOpenApp}
          onOpenDock={onOpenDock}
          shellTheme={shellTheme}
          threadId={threadId}
          user={user}
        />)}
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
