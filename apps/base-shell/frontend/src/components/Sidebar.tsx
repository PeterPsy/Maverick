import { useEffect, useRef, useState } from "react";
import type {
  CSSProperties,
  FocusEvent as ReactFocusEvent,
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
  TouchEvent as ReactTouchEvent,
} from "react";
import { AppRegistryItem, SessionUser, WorkspaceItem } from "../api";
import type { MaverickFrameScope } from "../iframePolicy";
import { isHorizontalIntent, isSidebarCloseSwipe, type SidebarSwipePoint } from "../lib/sidebarSwipe";
import { CHAT_APP_ID, SETTINGS_APP_ID, shellAppRailApps, shellVisibleApps } from "../navigation";
import { clampSidebarDetailsWidth, DEFAULT_SIDEBAR_DETAILS_WIDTH_PX } from "../session";
import type { SidebarMode } from "../session";
import type { ShellThemeMode, ShellThemeState } from "../theme";
import { DEFAULT_SHELL_THEME_MODE, DEFAULT_SHELL_THEME_STATE } from "../theme";
import { SidebarAppRail } from "./SidebarAppRail";
import { WidgetSlot } from "./WidgetSlot";
import type { WidgetPrimaryActionState } from "./WidgetSlot";
import { SidebarHeader } from "./SidebarHeader";
import { SidebarShellControls } from "./SidebarShellControls";
import { SidebarRailMenu } from "./SidebarRailMenu";
import { ThemeModeSwitcher } from "./ThemeModeSwitcher";

type TrackedSwipe = SidebarSwipePoint & {
  id: number;
};

export function Sidebar({
  activeAppId,
  activeAppParams,
  apps,
  activeWorkspaceId,
  frameScope,
  isLoading = false,
  isWorkspacesLoading = false,
  isOpen,
  isMobileLayout,
  isPinned,
  mode,
  mobilePrimaryActionRequestId,
  notifications,
  onClose,
  onModeChange,
  onOpenApp,
  onOpenSidebar,
  onPrimaryActionStateChange,
  onOpenSettings,
  onOpenAppSettings,
  onReorderPinnedApps,
  onSidebarDetailsWidthChange,
  onSidebarResizeActiveChange,
  onThemeModeChange = () => undefined,
  onWorkspaceChange,
  pinnedAppIds,
  railMetrics,
  sidebarDetailsWidthPx,
  shellTheme = DEFAULT_SHELL_THEME_STATE,
  themeMode = DEFAULT_SHELL_THEME_MODE,
  user,
  workspaces,
}: {
  activeAppId: string | null;
  activeAppParams: Record<string, string | boolean | null>;
  apps: AppRegistryItem[];
  activeWorkspaceId: string;
  frameScope: MaverickFrameScope;
  isOpen: boolean;
  isLoading?: boolean;
  isWorkspacesLoading?: boolean;
  isMobileLayout: boolean;
  isPinned: boolean;
  mode: SidebarMode;
  mobilePrimaryActionRequestId: number;
  notifications?: ReactNode;
  onClose: () => void;
  onModeChange: (mode: SidebarMode) => void;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  onOpenSidebar: () => void;
  onPrimaryActionStateChange: (state: WidgetPrimaryActionState) => void;
  onOpenSettings: () => void;
  onOpenAppSettings: () => void;
  onReorderPinnedApps: (appIds: string[]) => void;
  onSidebarDetailsWidthChange: (widthPx: number) => void;
  onSidebarResizeActiveChange?: (active: boolean) => void;
  onThemeModeChange?: (mode: ShellThemeMode) => void;
  onWorkspaceChange: (workspaceId: string) => Promise<void> | void;
  pinnedAppIds: string[];
  railMetrics: CSSProperties;
  sidebarDetailsWidthPx: number;
  shellTheme?: ShellThemeState;
  themeMode?: ShellThemeMode;
  user: SessionUser | null;
  workspaces: WorkspaceItem[];
}) {
  const closeSwipeStartRef = useRef<TrackedSwipe | null>(null);
  const resizeDragRef = useRef<{ pointerId: number; startWidthPx: number; startX: number } | null>(null);
  const [isRailReordering, setIsRailReordering] = useState(false);
  const [isResizeActive, setIsResizeActive] = useState(false);
  const [resizeHandleY, setResizeHandleY] = useState("50%");
  const visibleAppsById = new Map(shellVisibleApps(apps).map((app) => [app.app_id, app]));
  const railApps = shellAppRailApps(apps, pinnedAppIds);
  const activeApp = activeAppId ? visibleAppsById.get(activeAppId) || null : null;
  const settingsApp = visibleAppsById.get(SETTINGS_APP_ID) || null;
  const isInitialLoading = isLoading && railApps.length === 0;
  const sidebarEnabled = activeApp ? activeApp.sidebar_enabled !== false : !isLoading;
  const isDetailLayerOpen = sidebarEnabled && (isOpen || isPinned);
  const [hasMountedDetailWidgets, setHasMountedDetailWidgets] = useState(isDetailLayerOpen);
  const [mountedWidgetAppIds, setMountedWidgetAppIds] = useState<string[]>(activeAppId ? [activeAppId] : []);
  const visitedWidgetAppIds = activeAppId && !mountedWidgetAppIds.includes(activeAppId) ? [...mountedWidgetAppIds, activeAppId] : mountedWidgetAppIds;
  const renderedWidgetAppIds = visitedWidgetAppIds.filter((appId) => visibleAppsById.get(appId)?.sidebar_enabled !== false);
  const shouldMountDetailWidgets = hasMountedDetailWidgets || isDetailLayerOpen;
  const showMobileChatThemeSwitcher = isMobileLayout && activeAppId === CHAT_APP_ID;
  const sidebarFooterSlot = shouldMountDetailWidgets ? renderedWidgetAppIds.map((appId) => (
    <div aria-hidden={appId !== activeAppId} className="bs-sidebar__persistent-widget" data-active={appId === activeAppId} key={`footer:${activeWorkspaceId}:${appId}`}>
      <WidgetSlot
        activeWorkspaceId={activeWorkspaceId}
        content={{ active_app_id: activeAppId, active_app_params: activeAppParams, is_mobile_layout: isMobileLayout, placement: "sidebar-footer", user: user?.username || null }}
        contentKind="shell.sidebar.footer"
        frameScope={frameScope}
        hostAppId="base-shell"
        label="App sidebar footer"
        isActive={appId === activeAppId && isDetailLayerOpen}
        onCloseSidebar={onClose}
        onOpenApp={onOpenApp}
        onOpenSidebar={onOpenSidebar}
        onPrimaryActionStateChange={appId === activeAppId ? onPrimaryActionStateChange : undefined}
        preferredOwnerAppId={appId}
        primaryActionRequestId={appId === activeAppId ? mobilePrimaryActionRequestId : 0}
        shellTheme={shellTheme}
        size="compact"
      />
    </div>
  )) : null;

  useEffect(() => {
    if (isDetailLayerOpen) {
      setHasMountedDetailWidgets(true);
    }
  }, [isDetailLayerOpen]);

  useEffect(() => {
    if (!activeAppId) return;
    setMountedWidgetAppIds((current) => current.includes(activeAppId) ? current : [...current, activeAppId]);
  }, [activeAppId]);

  useEffect(() => {
    if (sidebarEnabled && shouldMountDetailWidgets) {
      return;
    }
    onPrimaryActionStateChange({
      available: false,
      label: "",
      preferredSurface: "app",
    });
  }, [onPrimaryActionStateChange, shouldMountDetailWidgets, sidebarEnabled]);

  function handlePointerEnter() {
    if (isMobileLayout || !sidebarEnabled) {
      return;
    }
    if (!isPinned) {
      onOpenSidebar();
    }
  }

  function handlePointerLeave(event: ReactMouseEvent<HTMLElement>) {
    if (isMobileLayout || !sidebarEnabled) {
      return;
    }
    if (isRailReordering || isResizeActive || resizeDragRef.current) {
      return;
    }
    if (!isPinned && !event.currentTarget.contains(document.activeElement)) {
      onClose();
    }
  }

  function handleFocus() {
    if (isMobileLayout || !sidebarEnabled) {
      return;
    }
    if (!isPinned) {
      onOpenSidebar();
    }
  }

  function handleBlur(event: ReactFocusEvent<HTMLElement>) {
    if (isMobileLayout || !sidebarEnabled) {
      return;
    }
    if (isRailReordering || isResizeActive || resizeDragRef.current) {
      return;
    }
    if (!isPinned && !event.currentTarget.contains(event.relatedTarget)) {
      onClose();
    }
  }

  function resetCloseSwipe() {
    closeSwipeStartRef.current = null;
  }

  function handleTouchStart(event: ReactTouchEvent<HTMLElement>) {
    if (!isMobileLayout || !isDetailLayerOpen || event.touches.length !== 1 || isSidebarSwipeIgnoredTarget(event.target)) {
      resetCloseSwipe();
      return;
    }
    const touch = event.touches[0];
    const start = { x: touch.clientX, y: touch.clientY };
    closeSwipeStartRef.current = { ...start, id: touch.identifier };
  }

  function handleTouchMove(event: ReactTouchEvent<HTMLElement>) {
    const start = closeSwipeStartRef.current;
    if (!isMobileLayout || !start) {
      return;
    }
    const touch = Array.from(event.changedTouches).find((item) => item.identifier === start.id);
    if (!touch) {
      return;
    }
    if (isHorizontalIntent(start, { x: touch.clientX, y: touch.clientY })) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (isSidebarCloseSwipe(start, { x: touch.clientX, y: touch.clientY })) {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      resetCloseSwipe();
    }
  }

  function handleResizePointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    if (isMobileLayout || !isDetailLayerOpen || event.button !== 0) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    updateResizeHandleY(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeDragRef.current = {
      pointerId: event.pointerId,
      startWidthPx: sidebarDetailsWidthPx,
      startX: event.clientX,
    };
    setIsResizeActive(true);
    onSidebarResizeActiveChange?.(true);
  }

  function handleResizePointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    updateResizeHandleY(event);
    const drag = resizeDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    onSidebarDetailsWidthChange(clampSidebarDetailsWidth(drag.startWidthPx + event.clientX - drag.startX));
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
    onSidebarResizeActiveChange?.(false);
  }

  function handleResizeKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (isMobileLayout || !sidebarEnabled) {
      return;
    }
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft" && event.key !== "Home") {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    if (event.key === "Home") {
      onSidebarDetailsWidthChange(DEFAULT_SIDEBAR_DETAILS_WIDTH_PX);
      return;
    }
    const direction = event.key === "ArrowRight" ? 1 : -1;
    onSidebarDetailsWidthChange(clampSidebarDetailsWidth(sidebarDetailsWidthPx + direction * 24));
  }

  return (
    <aside
      className={`bs-sidebar ${sidebarEnabled ? "" : "bs-sidebar--disabled"} bs-sidebar--${sidebarEnabled ? mode : "rail"} ${isDetailLayerOpen ? "is-open" : "is-closed"} ${isRailReordering ? "is-rail-reordering" : ""} ${isResizeActive ? "is-resizing" : ""}`}
      aria-label="Workspace navigation"
      onBlur={handleBlur}
      onFocus={handleFocus}
      onMouseEnter={handlePointerEnter}
      onMouseLeave={handlePointerLeave}
      onTouchCancel={resetCloseSwipe}
      onTouchEnd={resetCloseSwipe}
      onTouchMove={handleTouchMove}
      onTouchStart={handleTouchStart}
      style={railMetrics}
    >
      {!isMobileLayout ? (
        <div className="bs-sidebar__rail" aria-label="Applications">
          {!sidebarEnabled ? <SidebarRailMenu icon="workspaces" label="Controlli workspace" placement="top">
            <SidebarHeader activeApp={activeApp} activeWorkspaceId={activeWorkspaceId} isLoading={isLoading}
              notifications={notifications}
              isWorkspacesLoading={isWorkspacesLoading} onOpenAppSettings={onOpenAppSettings}
              onWorkspaceChange={onWorkspaceChange} workspaces={workspaces} />
          </SidebarRailMenu> : null}
          <SidebarAppRail
            activeAppId={activeAppId}
            appsToRender={railApps}
            enableReorder={true}
            isInitialLoading={isInitialLoading}
            onOpenApp={onOpenApp}
            onOpenSettings={onOpenSettings}
            onReorderActiveChange={setIsRailReordering}
            onReorderPinnedApps={onReorderPinnedApps}
            settingsApp={settingsApp}
          />
          {!sidebarEnabled ? <SidebarRailMenu icon="tune" label="Controlli Maverick" placement="bottom">
            <SidebarShellControls mode={mode} onModeChange={onModeChange} onThemeModeChange={onThemeModeChange}
              shellTheme={shellTheme} themeMode={themeMode} />
          </SidebarRailMenu> : null}
        </div>
      ) : null}

      {!sidebarEnabled && isMobileLayout ? <SidebarRailMenu icon="workspaces" label="Controlli workspace" placement="mobile"
        open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
        <SidebarHeader activeApp={activeApp} activeWorkspaceId={activeWorkspaceId} isLoading={isLoading}
          isWorkspacesLoading={isWorkspacesLoading} onOpenAppSettings={onOpenAppSettings}
          onWorkspaceChange={onWorkspaceChange} workspaces={workspaces} />
        <SidebarShellControls mode={mode} onModeChange={onModeChange} onThemeModeChange={onThemeModeChange}
          shellTheme={shellTheme} themeMode={themeMode} />
      </SidebarRailMenu> : null}
      <div className="bs-sidebar__details" aria-hidden={!isDetailLayerOpen}>
        <div className="bs-sidebar__top-overlay">
          {sidebarEnabled ? <SidebarHeader
            activeApp={activeApp}
            activeWorkspaceId={activeWorkspaceId}
            isLoading={isLoading}
            isWorkspacesLoading={isWorkspacesLoading}
            onOpenAppSettings={onOpenAppSettings}
            notifications={notifications}
            onWorkspaceChange={onWorkspaceChange}
            workspaces={workspaces}
          /> : null}

        </div>

        {shouldMountDetailWidgets ? renderedWidgetAppIds.map((appId) => (
          <div aria-hidden={appId !== activeAppId} className="bs-sidebar__persistent-widget bs-sidebar__persistent-widget--fill" data-active={appId === activeAppId} key={`primary:${activeWorkspaceId}:${appId}`}>
            <WidgetSlot
              activeWorkspaceId={activeWorkspaceId}
              content={{ active_app_id: activeAppId, active_app_params: activeAppParams, is_mobile_layout: isMobileLayout, user: user?.username || null }}
              contentKind="shell.sidebar.primary"
              frameScope={frameScope}
              hostAppId="base-shell"
              label="App sidebar content"
              isActive={appId === activeAppId && isDetailLayerOpen}
              onCloseSidebar={onClose}
              onOpenApp={onOpenApp}
              onOpenSidebar={onOpenSidebar}
              preferredOwnerAppId={appId}
              shellTheme={shellTheme}
            />
          </div>
        )) : null}

        <div className="bs-sidebar__bottom-fixed">
          {showMobileChatThemeSwitcher ? (
            <div className="bs-sidebar__mobile-chat-footer-row">
              {sidebarFooterSlot}
              <ThemeModeSwitcher
                className="bs-sidebar__mobile-chat-theme-switcher"
                onThemeModeChange={onThemeModeChange}
                themeMode={themeMode}
              />
            </div>
          ) : (
            sidebarFooterSlot
          )}

          {!isMobileLayout && sidebarEnabled ? (
            <SidebarShellControls
              mode={mode}
              onModeChange={onModeChange}
              onThemeModeChange={onThemeModeChange}
              shellTheme={shellTheme}
              themeMode={themeMode}
              onClose={sidebarEnabled && !isPinned ? onClose : undefined}
            />
          ) : null}
        </div>
      </div>
      {!isMobileLayout && isDetailLayerOpen ? (
        <button
          aria-label="Ridimensiona sidebar"
          className="bs-sidebar__resize-handle"
          onKeyDown={handleResizeKeyDown}
          onPointerCancel={handleResizePointerEnd}
          onPointerDown={handleResizePointerDown}
          onPointerEnter={updateResizeHandleY}
          onPointerMove={handleResizePointerMove}
          onPointerUp={handleResizePointerEnd}
          style={{ "--bs-sidebar-resize-icon-y": resizeHandleY } as CSSProperties}
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-rounded">arrow_right_alt</span>
        </button>
      ) : null}
    </aside>
  );
}

function isSidebarSwipeIgnoredTarget(target: EventTarget): boolean {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(target.closest("input, textarea, select, [contenteditable='true'], [data-no-sidebar-swipe]"));
}

export { sidebarRailButtonClassName } from "./SidebarAppRail";
