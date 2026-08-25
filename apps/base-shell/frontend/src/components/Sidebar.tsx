import { useEffect, useRef, useState } from "react";
import type {
  CSSProperties,
  FocusEvent as ReactFocusEvent,
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
  TouchEvent as ReactTouchEvent,
} from "react";
import { AppRegistryItem, SessionUser, WorkspaceItem } from "../api";
import { isHorizontalIntent, isSidebarCloseSwipe, type SidebarSwipePoint } from "../lib/sidebarSwipe";
import { CHAT_APP_ID, SETTINGS_APP_ID, shellAppRailApps, shellVisibleApps } from "../navigation";
import { clampSidebarDetailsWidth, DEFAULT_SIDEBAR_DETAILS_WIDTH_PX } from "../session";
import type { SidebarMode } from "../session";
import type { ShellThemeMode, ShellThemeState } from "../theme";
import { DEFAULT_SHELL_THEME_MODE, DEFAULT_SHELL_THEME_STATE } from "../theme";
import { AppLogo } from "./AppLogo";
import { BrandMark } from "./BrandMark";
import { SidebarAppRail } from "./SidebarAppRail";
import { sidebarLogoSrc } from "./sidebarLogo";
import { WidgetSlot } from "./WidgetSlot";
import type { WidgetPrimaryActionState } from "./WidgetSlot";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

type TrackedSwipe = SidebarSwipePoint & {
  id: number;
};

export function Sidebar({
  activeAppId,
  activeAppParams,
  apps,
  activeWorkspaceId,
  isLoading = false,
  isWorkspacesLoading = false,
  isOpen,
  isMobileLayout,
  isPinned,
  mode,
  mobilePrimaryActionRequestId,
  onClose,
  onModeChange,
  onOpenApp,
  onOpenSidebar,
  onPrimaryActionStateChange,
  onOpenSettings,
  onReorderPinnedApps,
  onSidebarDetailsWidthChange,
  onSidebarResizeActiveChange,
  onThemeModeChange = () => undefined,
  onWorkspaceChanged,
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
  isOpen: boolean;
  isLoading?: boolean;
  isWorkspacesLoading?: boolean;
  isMobileLayout: boolean;
  isPinned: boolean;
  mode: SidebarMode;
  mobilePrimaryActionRequestId: number;
  onClose: () => void;
  onModeChange: (mode: SidebarMode) => void;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  onOpenSidebar: () => void;
  onPrimaryActionStateChange: (state: WidgetPrimaryActionState) => void;
  onOpenSettings: () => void;
  onReorderPinnedApps: (appIds: string[]) => void;
  onSidebarDetailsWidthChange: (widthPx: number) => void;
  onSidebarResizeActiveChange?: (active: boolean) => void;
  onThemeModeChange?: (mode: ShellThemeMode) => void;
  onWorkspaceChanged: () => void;
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
  const logoSrc = sidebarLogoSrc(shellTheme);
  const visibleAppsById = new Map(shellVisibleApps(apps).map((app) => [app.app_id, app]));
  const railApps = shellAppRailApps(apps, pinnedAppIds);
  const activeApp = activeAppId ? visibleAppsById.get(activeAppId) || null : null;
  const settingsApp = visibleAppsById.get(SETTINGS_APP_ID) || null;
  const isInitialLoading = isLoading && railApps.length === 0;
  const isDetailLayerOpen = isOpen || isPinned;
  const [hasMountedDetailWidgets, setHasMountedDetailWidgets] = useState(isDetailLayerOpen);
  const [mountedWidgetAppIds, setMountedWidgetAppIds] = useState<string[]>(activeAppId ? [activeAppId] : []);
  const renderedWidgetAppIds = activeAppId && !mountedWidgetAppIds.includes(activeAppId) ? [...mountedWidgetAppIds, activeAppId] : mountedWidgetAppIds;
  const shouldMountDetailWidgets = hasMountedDetailWidgets || isDetailLayerOpen;
  const showMobileChatThemeSwitcher = isMobileLayout && activeAppId === CHAT_APP_ID;
  const sidebarFooterSlot = shouldMountDetailWidgets ? renderedWidgetAppIds.map((appId) => (
    <div aria-hidden={appId !== activeAppId} className="bs-sidebar__persistent-widget" data-active={appId === activeAppId} key={`footer:${activeWorkspaceId}:${appId}`}>
      <WidgetSlot
        activeWorkspaceId={activeWorkspaceId}
        content={{ active_app_id: activeAppId, active_app_params: activeAppParams, is_mobile_layout: isMobileLayout, placement: "sidebar-footer", user: user?.username || null }}
        contentKind="shell.sidebar.footer"
        hostAppId="base-shell"
        label="App sidebar footer"
        isActive={appId === activeAppId}
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
    if (shouldMountDetailWidgets) {
      return;
    }
    onPrimaryActionStateChange({
      available: false,
      label: "",
      preferredSurface: "app",
    });
  }, [onPrimaryActionStateChange, shouldMountDetailWidgets]);

  function handlePointerEnter() {
    if (isMobileLayout) {
      return;
    }
    if (!isPinned) {
      onOpenSidebar();
    }
  }

  function handlePointerLeave(event: ReactMouseEvent<HTMLElement>) {
    if (isMobileLayout) {
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
    if (isMobileLayout) {
      return;
    }
    if (!isPinned) {
      onOpenSidebar();
    }
  }

  function handleBlur(event: ReactFocusEvent<HTMLElement>) {
    if (isMobileLayout) {
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
    if (isMobileLayout) {
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
      className={`bs-sidebar bs-sidebar--${mode} ${isDetailLayerOpen ? "is-open" : "is-closed"} ${isRailReordering ? "is-rail-reordering" : ""} ${isResizeActive ? "is-resizing" : ""}`}
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
        </div>
      ) : null}

      <div className="bs-sidebar__details" aria-hidden={!isDetailLayerOpen}>
        <div className="bs-sidebar__top-overlay">
          <div className="bs-sidebar__header">
            {activeApp ? (
              <AppLogo app={activeApp} className="bs-sidebar__brand-mark" />
            ) : isLoading ? (
              <span className="bs-sidebar__brand-mark bs-sidebar__brand-mark-skeleton" aria-hidden="true" />
            ) : (
              <BrandMark className="bs-sidebar__brand-mark" />
            )}
            <WorkspaceSwitcher
              activeWorkspaceId={activeWorkspaceId}
              canCreateWorkspace={user?.platform_role === "admin"}
              isLoading={isWorkspacesLoading}
              onChanged={onWorkspaceChanged}
              workspaces={workspaces}
            />
          </div>

        </div>

        {shouldMountDetailWidgets ? renderedWidgetAppIds.map((appId) => (
          <div aria-hidden={appId !== activeAppId} className="bs-sidebar__persistent-widget bs-sidebar__persistent-widget--fill" data-active={appId === activeAppId} key={`primary:${activeWorkspaceId}:${appId}`}>
            <WidgetSlot
              activeWorkspaceId={activeWorkspaceId}
              content={{ active_app_id: activeAppId, active_app_params: activeAppParams, is_mobile_layout: isMobileLayout, user: user?.username || null }}
              contentKind="shell.sidebar.primary"
              hostAppId="base-shell"
              label="App sidebar content"
              isActive={appId === activeAppId}
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

          {!isMobileLayout ? (
            <div className="bs-sidebar__shell-controls">
              <img alt="" aria-hidden="true" className="bs-sidebar__desktop-logo" src={logoSrc} />
              <div className="bs-sidebar__control-cluster">
                <ThemeModeSwitcher onThemeModeChange={onThemeModeChange} themeMode={themeMode} />
                <div className="bs-sidebar__mode-switcher" aria-label="Sidebar mode">
                  <button
                    aria-label="Solo app in overlay"
                    aria-pressed={mode === "rail"}
                    className={`bs-sidebar__mode-button ${mode === "rail" ? "is-active" : ""}`}
                    onClick={() => onModeChange("rail")}
                    title="Solo app in overlay"
                    type="button"
                  >
                    <span aria-hidden="true" className="material-symbols-rounded">dock_to_left</span>
                  </button>
                  <button
                    aria-label="Sidebar fissa"
                    aria-pressed={mode === "fixed"}
                    className={`bs-sidebar__mode-button ${mode === "fixed" ? "is-active" : ""}`}
                    onClick={() => onModeChange("fixed")}
                    title="Sidebar fissa"
                    type="button"
                  >
                    <span aria-hidden="true" className="material-symbols-rounded">left_panel_close</span>
                  </button>
                </div>
                {!isPinned ? (
                  <button aria-label="Chiudi pannello laterale" className="bs-panel-minimize" onClick={onClose} title="Chiudi pannello laterale" type="button">
                    <span aria-hidden="true" className="material-symbols-rounded">chevron_left</span>
                  </button>
                ) : null}
              </div>
            </div>
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

function ThemeModeSwitcher({
  className = "",
  onThemeModeChange,
  themeMode,
}: {
  className?: string;
  onThemeModeChange: (mode: ShellThemeMode) => void;
  themeMode: ShellThemeMode;
}) {
  const classNames = ["bs-sidebar__theme-switcher", className].filter(Boolean).join(" ");
  return (
    <div className={classNames} aria-label="Theme mode">
      <ThemeModeButton
        active={themeMode === "dark"}
        icon="dark_mode"
        label="Dark mode"
        mode="dark"
        onThemeModeChange={onThemeModeChange}
      />
      <ThemeModeButton
        active={themeMode === "light"}
        icon="light_mode"
        label="Light mode"
        mode="light"
        onThemeModeChange={onThemeModeChange}
      />
      <ThemeModeButton
        active={themeMode === "system"}
        icon="desktop_windows"
        label="System mode"
        mode="system"
        onThemeModeChange={onThemeModeChange}
      />
    </div>
  );
}

function ThemeModeButton({
  active,
  icon,
  label,
  mode,
  onThemeModeChange,
}: {
  active: boolean;
  icon: string;
  label: string;
  mode: ShellThemeMode;
  onThemeModeChange: (mode: ShellThemeMode) => void;
}) {
  return (
    <button
      aria-label={label}
      aria-pressed={active}
      className={`bs-sidebar__mode-button ${active ? "is-active" : ""}`}
      onClick={() => onThemeModeChange(mode)}
      title={label}
      type="button"
    >
      <span aria-hidden="true" className="material-symbols-rounded">{icon}</span>
    </button>
  );
}

function isSidebarSwipeIgnoredTarget(target: EventTarget): boolean {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(target.closest("input, textarea, select, [contenteditable='true'], [data-no-sidebar-swipe]"));
}

export { sidebarRailButtonClassName } from "./SidebarAppRail";
