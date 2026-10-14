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
  maxWidthPx = clampFloatingChatWidth(720),
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
  maxWidthPx?: number;
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
  const [mountedScope, setMountedScope] = useState(isVisible ? scope : "");
  useEffect(() => {
    if (isVisible) setMountedScope(scope);
  }, [scope, isVisible]);

  useEffect(() => {
    if (!isVisible || !isMobileMode) return;
    const surface = document.querySelector(".bs-floating-chat-host__surface");
    const focus = () => surface?.querySelector<HTMLIFrameElement>("iframe")?.focus();
    focus();
    surface?.addEventListener("load", focus, true);
    return () => surface?.removeEventListener("load", focus, true);
  }, [isVisible, isMobileMode]);

  if (!isVisible && mountedScope !== scope) return null;

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
    onWidthChange(clampFloatingChatWidth(Math.min(maxWidthPx, drag.startWidthPx + drag.startX - event.clientX)));
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
    if (!isDockMode || (event.key !== "ArrowRight" && event.key !== "ArrowLeft" && event.key !== "Home" && event.key !== "End")) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    if (event.key === "End") { onWidthChange(maxWidthPx); return; }
    if (event.key === "Home") {
      onWidthChange(clampFloatingChatWidth(Math.min(maxWidthPx, 420)));
      return;
    }
    const direction = event.key === "ArrowLeft" ? 1 : -1;
    onWidthChange(clampFloatingChatWidth(Math.min(maxWidthPx, widthPx + direction * 24)));
  }

  return (
    <section
      aria-hidden={!isVisible}
      inert={!isVisible}
      aria-label={isMobileMode ? "Chat contestuale" : isDockMode ? "Right dock panel" : "Shell overlay widgets"}
      className={`bs-floating-chat-host is-${placement} ${isVisible ? "is-visible" : ""} ${isMobileChatClosing ? "is-closing" : ""} ${isResizeActive ? "is-resizing" : ""}`}
    >
      <div className="bs-floating-chat-host__surface">
        <FloatingChatWidget
          key={scope}
          placement={placement}
          visible={isVisible}
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
        />
      </div>
      <button
        aria-label="Ridimensiona chat laterale"
        role="separator"
        aria-orientation="vertical"
        aria-valuemin={360}
        aria-valuemax={maxWidthPx}
        aria-valuenow={widthPx}
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
