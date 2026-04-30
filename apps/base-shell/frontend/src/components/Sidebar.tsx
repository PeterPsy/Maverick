import { useRef } from "react";
import type { CSSProperties, FocusEvent as ReactFocusEvent, MouseEvent as ReactMouseEvent, TouchEvent as ReactTouchEvent } from "react";
import { AppRegistryItem, SessionUser, WorkspaceItem } from "../api";
import { shellVisibleApps } from "../navigation";
import type { SidebarMode } from "../session";
import { AppLogo } from "./AppLogo";
import { BrandMark } from "./BrandMark";
import { WidgetSlot } from "./WidgetSlot";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

type SwipePoint = {
  x: number;
  y: number;
};

type TrackedSwipe = SwipePoint & {
  id: number;
};

const SIDEBAR_SWIPE_MIN_DISTANCE = 72;
const SIDEBAR_SWIPE_MAX_VERTICAL_DRIFT = 48;

export function Sidebar({
  activeAppId,
  apps,
  activeWorkspaceId,
  isLoading = false,
  isOpen,
  isMobileLayout,
  isPinned,
  mode,
  onClose,
  onModeChange,
  onOpenApp,
  onOpenSidebar,
  onOpenSettings,
  onWorkspaceChanged,
  pinnedAppIds,
  user,
  workspaces,
}: {
  activeAppId: string | null;
  apps: AppRegistryItem[];
  activeWorkspaceId: string;
  isOpen: boolean;
  isLoading?: boolean;
  isMobileLayout: boolean;
  isPinned: boolean;
  mode: SidebarMode;
  onClose: () => void;
  onModeChange: (mode: SidebarMode) => void;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  onOpenSidebar: () => void;
  onOpenSettings: () => void;
  onWorkspaceChanged: () => void;
  pinnedAppIds: string[];
  user: SessionUser | null;
  workspaces: WorkspaceItem[];
}) {
  const closeSwipeStartRef = useRef<TrackedSwipe | null>(null);
  const visibleAppsById = new Map(shellVisibleApps(apps).map((app) => [app.app_id, app]));
  const pinnedApps = pinnedAppIds.map((appId) => visibleAppsById.get(appId)).filter((app): app is AppRegistryItem => Boolean(app));
  const activeApp = activeAppId ? visibleAppsById.get(activeAppId) || null : null;
  const isInitialLoading = isLoading && pinnedApps.length === 0;
  const railMetrics = sidebarRailMetrics(isInitialLoading ? 4 : pinnedApps.length + 1);
  const isDetailLayerOpen = isOpen || isPinned;

  function handlePointerEnter() {
    if (!isPinned) {
      onOpenSidebar();
    }
  }

  function handlePointerLeave(event: ReactMouseEvent<HTMLElement>) {
    if (!isPinned && !event.currentTarget.contains(document.activeElement)) {
      onClose();
    }
  }

  function handleFocus() {
    if (!isPinned) {
      onOpenSidebar();
    }
  }

  function handleBlur(event: ReactFocusEvent<HTMLElement>) {
    if (!isPinned && !event.currentTarget.contains(event.relatedTarget)) {
      onClose();
    }
  }

  function handleOpenApp(appId: string) {
    onOpenApp(appId);
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

  function renderPinnedAppRail(extraClassName = "") {
    const className = extraClassName ? `bs-sidebar__rail-apps ${extraClassName}` : "bs-sidebar__rail-apps";
    if (isInitialLoading) {
      return (
        <div className={`${className} is-loading`} role="list" aria-hidden="true">
          {Array.from({ length: 4 }).map((_, index) => (
            <div className="bs-sidebar__rail-item" key={index} role="listitem">
              <span className="bs-app-logo bs-app-logo--rail bs-sidebar__rail-skeleton-logo" />
            </div>
          ))}
        </div>
      );
    }
    return (
      <div className={className} role="list">
        {pinnedApps.map((app) => (
          <div className="bs-sidebar__rail-item" key={app.app_id} role="listitem">
            <button
              aria-current={activeAppId === app.app_id ? "page" : undefined}
              aria-label={app.name}
              className={`bs-sidebar__rail-button ${activeAppId === app.app_id ? "is-active" : ""}`}
              onClick={() => handleOpenApp(app.app_id)}
              title={app.name}
              type="button"
            >
              <AppLogo app={app} className="bs-app-logo--rail" />
              <span className="bs-sidebar__rail-tooltip" role="tooltip">{app.name}</span>
            </button>
          </div>
        ))}
        <div className="bs-sidebar__rail-item" role="listitem">
          <button
            aria-label="Settings"
            className="bs-sidebar__rail-button"
            onClick={onOpenSettings}
            title="Settings"
            type="button"
          >
            <span className="bs-app-logo is-glyph bs-app-logo--rail">
              <span aria-hidden="true" className="material-symbols-rounded">settings</span>
            </span>
            <span className="bs-sidebar__rail-tooltip" role="tooltip">Settings</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <aside
      className={`bs-sidebar bs-sidebar--${mode} ${isDetailLayerOpen ? "is-open" : "is-closed"}`}
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
      <div className="bs-sidebar__rail" aria-label="Applications">
        {renderPinnedAppRail()}
      </div>

      <div className="bs-sidebar__details" aria-hidden={!isDetailLayerOpen}>
        <div className="bs-sidebar__top-overlay">
          <div className="bs-sidebar__header">
            {activeApp ? <AppLogo app={activeApp} className="bs-sidebar__brand-mark" /> : <BrandMark className="bs-sidebar__brand-mark" />}
            <WorkspaceSwitcher
              activeWorkspaceId={activeWorkspaceId}
              canCreateWorkspace={user?.platform_role === "admin"}
              onChanged={onWorkspaceChanged}
              workspaces={workspaces}
            />
          </div>

          <div className="bs-sidebar__mobile-apps" aria-label="Applicazioni pinnate" data-no-sidebar-swipe="">
            {renderPinnedAppRail("bs-sidebar__rail-apps--mobile")}
          </div>
        </div>

        <WidgetSlot
          activeWorkspaceId={activeWorkspaceId}
          content={{ is_mobile_layout: isMobileLayout, user: user?.username || null }}
          contentKind="shell.sidebar.primary"
          hostAppId="base-shell"
          label="Chat projects and conversations"
          onCloseSidebar={onClose}
          onOpenApp={onOpenApp}
        />

        <div className="bs-sidebar__shell-controls">
          {!isMobileLayout ? (
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
          ) : null}
          {!isPinned && !isMobileLayout ? (
            <button aria-label="Chiudi pannello laterale" className="bs-panel-minimize" onClick={onClose} title="Chiudi pannello laterale" type="button">
              <span aria-hidden="true" className="material-symbols-rounded">chevron_left</span>
            </button>
          ) : null}
        </div>
      </div>
    </aside>
  );
}

function isSidebarCloseSwipe(start: SwipePoint, end: SwipePoint): boolean {
  const deltaX = end.x - start.x;
  const deltaY = Math.abs(end.y - start.y);
  return deltaX <= -SIDEBAR_SWIPE_MIN_DISTANCE && deltaY <= SIDEBAR_SWIPE_MAX_VERTICAL_DRIFT;
}

function isHorizontalIntent(start: SwipePoint, current: SwipePoint): boolean {
  const deltaX = Math.abs(current.x - start.x);
  const deltaY = Math.abs(current.y - start.y);
  return deltaX > 12 && deltaX > deltaY;
}

function isSidebarSwipeIgnoredTarget(target: EventTarget): boolean {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(target.closest("input, textarea, select, [contenteditable='true'], .bs-sidebar__mobile-apps, [data-no-sidebar-swipe]"));
}

export function sidebarRailMetrics(appCount: number): CSSProperties {
  const iconSize = appCount <= 5 ? 3 : appCount <= 7 ? 2.8 : appCount <= 9 ? 2.55 : appCount <= 12 ? 2.3 : 2.05;
  const railWidth = iconSize + 0.95;
  return {
    "--bs-sidebar-icon-size": `${iconSize}rem`,
    "--bs-sidebar-rail-width": `${railWidth}rem`,
  } as CSSProperties;
}
