import { useRef, useState } from "react";
import type {
  CSSProperties,
  FocusEvent as ReactFocusEvent,
  MouseEvent as ReactMouseEvent,
  TouchEvent as ReactTouchEvent,
} from "react";
import { AppRegistryItem, SessionUser, WorkspaceItem } from "../api";
import { isHorizontalIntent, isSidebarCloseSwipe, type SidebarSwipePoint } from "../lib/sidebarSwipe";
import { shellAppRailApps, shellVisibleApps } from "../navigation";
import type { SidebarMode } from "../session";
import { AppLogo } from "./AppLogo";
import { BrandMark } from "./BrandMark";
import { SidebarAppRail } from "./SidebarAppRail";
import { WidgetSlot } from "./WidgetSlot";
import type { WidgetPrimaryActionState } from "./WidgetSlot";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";

const SIDEBAR_DESKTOP_LOGO_SRC = "/apps/base-shell/sidebar-logo.svg";

type TrackedSwipe = SidebarSwipePoint & {
  id: number;
};

export function Sidebar({
  activeAppId,
  activeAppParams,
  apps,
  activeWorkspaceId,
  isLoading = false,
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
  onWorkspaceChanged,
  pinnedAppIds,
  railMetrics,
  user,
  workspaces,
}: {
  activeAppId: string | null;
  activeAppParams: Record<string, string | boolean | null>;
  apps: AppRegistryItem[];
  activeWorkspaceId: string;
  isOpen: boolean;
  isLoading?: boolean;
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
  onWorkspaceChanged: () => void;
  pinnedAppIds: string[];
  railMetrics: CSSProperties;
  user: SessionUser | null;
  workspaces: WorkspaceItem[];
}) {
  const closeSwipeStartRef = useRef<TrackedSwipe | null>(null);
  const [isRailReordering, setIsRailReordering] = useState(false);
  const visibleAppsById = new Map(shellVisibleApps(apps).map((app) => [app.app_id, app]));
  const railApps = shellAppRailApps(apps, pinnedAppIds);
  const activeApp = activeAppId ? visibleAppsById.get(activeAppId) || null : null;
  const isInitialLoading = isLoading && railApps.length === 0;
  const isDetailLayerOpen = isOpen || isPinned;

  function handlePointerEnter() {
    if (!isPinned) {
      onOpenSidebar();
    }
  }

  function handlePointerLeave(event: ReactMouseEvent<HTMLElement>) {
    if (isRailReordering) {
      return;
    }
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
    if (isRailReordering) {
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

  return (
    <aside
      className={`bs-sidebar bs-sidebar--${mode} ${isDetailLayerOpen ? "is-open" : "is-closed"} ${isRailReordering ? "is-rail-reordering" : ""}`}
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
        <SidebarAppRail
          activeAppId={activeAppId}
          appsToRender={railApps}
          enableReorder={!isMobileLayout}
          isInitialLoading={isInitialLoading}
          onOpenApp={onOpenApp}
          onOpenSettings={onOpenSettings}
          onReorderActiveChange={setIsRailReordering}
          onReorderPinnedApps={onReorderPinnedApps}
        />
      </div>

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
              isLoading={isLoading}
              onChanged={onWorkspaceChanged}
              workspaces={workspaces}
            />
          </div>

          <div className="bs-sidebar__mobile-apps" aria-label="Applicazioni pinnate" data-no-sidebar-swipe="">
            <SidebarAppRail
              activeAppId={activeAppId}
              appsToRender={sidebarMobileRailApps(railApps, activeAppId)}
              className="bs-sidebar__rail-apps--mobile"
              enableReorder={false}
              isInitialLoading={isInitialLoading}
              onOpenApp={onOpenApp}
              onOpenSettings={onOpenSettings}
              onReorderPinnedApps={onReorderPinnedApps}
            />
          </div>
        </div>

        <WidgetSlot
          activeWorkspaceId={activeWorkspaceId}
          content={{ active_app_id: activeAppId, active_app_params: activeAppParams, is_mobile_layout: isMobileLayout, user: user?.username || null }}
          contentKind="shell.sidebar.primary"
          hostAppId="base-shell"
          label="App sidebar content"
          onCloseSidebar={onClose}
          onOpenApp={onOpenApp}
          preferredOwnerAppId={activeAppId}
        />

        <div className="bs-sidebar__bottom-fixed">
          <WidgetSlot
            activeWorkspaceId={activeWorkspaceId}
            content={{ active_app_id: activeAppId, active_app_params: activeAppParams, is_mobile_layout: isMobileLayout, placement: "sidebar-footer", user: user?.username || null }}
            contentKind="shell.sidebar.footer"
            hostAppId="base-shell"
            label="App sidebar footer"
            onCloseSidebar={onClose}
            onOpenApp={onOpenApp}
            onPrimaryActionStateChange={onPrimaryActionStateChange}
            preferredOwnerAppId={activeAppId}
            primaryActionRequestId={mobilePrimaryActionRequestId}
            size="compact"
          />

          <div className="bs-sidebar__shell-controls">
            {!isMobileLayout ? (
              <img alt="" aria-hidden="true" className="bs-sidebar__desktop-logo" src={SIDEBAR_DESKTOP_LOGO_SRC} />
            ) : null}
            {!isMobileLayout ? (
              <div className="bs-sidebar__control-cluster">
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
            ) : null}
          </div>
        </div>
      </div>
    </aside>
  );
}

function isSidebarSwipeIgnoredTarget(target: EventTarget): boolean {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(target.closest("input, textarea, select, [contenteditable='true'], .bs-sidebar__mobile-apps, [data-no-sidebar-swipe]"));
}

export function sidebarMobileRailApps(railApps: AppRegistryItem[], activeAppId: string | null): AppRegistryItem[] {
  if (!activeAppId) {
    return railApps;
  }
  const normalizedActiveAppId = activeAppId.toLowerCase();
  return railApps.filter((app) => app.app_id.toLowerCase() !== normalizedActiveAppId);
}

export { sidebarRailButtonClassName } from "./SidebarAppRail";
