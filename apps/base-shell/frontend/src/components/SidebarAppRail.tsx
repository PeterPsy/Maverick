import { useEffect } from "react";
import type { CSSProperties, MouseEvent as ReactMouseEvent } from "react";
import type { AppRegistryItem } from "../api";
import { useSidebarRailReorder, type ActiveRailReorder } from "../hooks/useSidebarRailReorder";
import { reorderByTargetIndex } from "../lib/sidebarRailReorder";
import { APP_STORE_APP_ID } from "../navigation";
import { AppLogo } from "./AppLogo";

export function SidebarAppRail({
  activeAppId,
  appsToRender,
  className = "",
  enableReorder,
  isInitialLoading,
  onOpenApp,
  onOpenSettings,
  onReorderPinnedApps,
  onReorderActiveChange,
}: {
  activeAppId: string | null;
  appsToRender: AppRegistryItem[];
  className?: string;
  enableReorder: boolean;
  isInitialLoading: boolean;
  onOpenApp: (appId: string) => void;
  onOpenSettings: () => void;
  onReorderActiveChange?: (active: boolean) => void;
  onReorderPinnedApps: (appIds: string[]) => void;
}) {
  const reorderableRailAppIds = appsToRender.filter((app) => isDesktopRailReorderableApp(app.app_id)).map((app) => app.app_id);
  const canReorder = enableReorder && reorderableRailAppIds.length > 1;
  const {
    activeRailReorder,
    handleRailKeyDown,
    handleRailPointerCancel,
    handleRailPointerDown,
    handleRailPointerMove,
    handleRailPointerUp,
    keyboardReorderStatus,
    railAppsContainerRef,
    setRailItemRef,
    suppressClickIfNeeded,
  } = useSidebarRailReorder({
    canReorder,
    getAppName: (appId) => appsToRender.find((app) => app.app_id === appId)?.name || appId,
    onReorderPinnedApps,
    reorderableAppIds: reorderableRailAppIds,
  });
  const baseClassName = className ? `bs-sidebar__rail-apps ${className}` : "bs-sidebar__rail-apps";
  const renderedApps = canReorder ? reorderedRailAppsForRender(appsToRender, activeRailReorder) : appsToRender;
  const renderedReorderableIds = renderedApps.filter((app) => isDesktopRailReorderableApp(app.app_id)).map((app) => app.app_id);
  const draggingRailApp = activeRailReorder ? appsToRender.find((app) => app.app_id === activeRailReorder.appId) ?? null : null;
  const isReorderActive = Boolean(activeRailReorder);
  const ghostStyle = activeRailReorder ? railDragGhostStyle(activeRailReorder, railAppsContainerRef.current) : undefined;

  function handleOpenApp(appId: string, event?: ReactMouseEvent<HTMLButtonElement>) {
    if (suppressClickIfNeeded(appId, event)) {
      return;
    }
    onOpenApp(appId);
  }

  useEffect(() => {
    onReorderActiveChange?.(isReorderActive);
    return () => onReorderActiveChange?.(false);
  }, [isReorderActive, onReorderActiveChange]);

  if (isInitialLoading) {
    return (
      <div className={`${baseClassName} is-loading`} role="list" aria-hidden="true">
        {Array.from({ length: 4 }).map((_, index) => (
          <div className="bs-sidebar__rail-item" key={index} role="listitem">
            <span className="bs-app-logo bs-app-logo--rail bs-sidebar__rail-skeleton-logo" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <>
      <div className={baseClassName} ref={canReorder ? railAppsContainerRef : undefined} role="list">
        {renderedApps.map((app) => {
          const reorderableIndex = renderedReorderableIds.indexOf(app.app_id);
          const isReorderable = canReorder && reorderableIndex >= 0;
          const isDragging = activeRailReorder?.appId === app.app_id;
          const isDropTarget = isReorderable && activeRailReorder?.targetIndex === reorderableIndex;
          return (
            <div
              className={sidebarRailItemClassName({ isDragging, isDropTarget })}
              key={app.app_id}
              ref={(element) => setRailItemRef(app.app_id, element)}
              role="listitem"
            >
              <button
                aria-current={activeAppId === app.app_id ? "page" : undefined}
                aria-keyshortcuts={isReorderable ? "Alt+ArrowUp Alt+ArrowDown" : undefined}
                aria-label={isReorderable ? `${app.name}. Alt+ArrowUp or Alt+ArrowDown to reorder.` : app.name}
                className={sidebarRailButtonClassName(app.app_id, activeAppId, { isDragging, isDropTarget, isReorderable })}
                onClick={(event) => handleOpenApp(app.app_id, event)}
                onKeyDown={(event) => handleRailKeyDown(app.app_id, event)}
                onPointerCancel={isReorderable ? handleRailPointerCancel : undefined}
                onPointerDown={isReorderable ? (event) => handleRailPointerDown(app.app_id, event) : undefined}
                onPointerMove={isReorderable ? handleRailPointerMove : undefined}
                onPointerUp={isReorderable ? handleRailPointerUp : undefined}
                title={activeRailReorder ? undefined : app.name}
                type="button"
              >
                <AppLogo app={app} className="bs-app-logo--rail" />
                <span className="bs-sidebar__rail-tooltip" role="tooltip">{app.name}</span>
              </button>
            </div>
          );
        })}
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
        <span className="bs-sidebar__rail-status" aria-live="polite">{keyboardReorderStatus}</span>
      </div>
      {draggingRailApp ? (
        <div
          className="bs-sidebar__rail-drag-ghost"
          style={ghostStyle}
        >
          <AppLogo app={draggingRailApp} className="bs-app-logo--rail" />
        </div>
      ) : null}
    </>
  );
}

function railDragGhostStyle(activeReorder: ActiveRailReorder, container: HTMLDivElement | null): CSSProperties {
  if (!container) {
    return { left: `${activeReorder.currentX}px`, top: `${activeReorder.currentY}px` };
  }
  const rect = container.getBoundingClientRect();
  const firstButton = container.querySelector(".bs-sidebar__rail-button");
  const buttonRect = firstButton instanceof HTMLElement ? firstButton.getBoundingClientRect() : null;
  const halfIcon = Math.max(12, (buttonRect?.height || 48) / 2);
  const minY = rect.top + halfIcon;
  const maxY = rect.bottom - halfIcon;
  const clampedY = maxY >= minY ? clamp(activeReorder.currentY, minY, maxY) : (rect.top + rect.bottom) / 2;
  return {
    left: `${(rect.left + rect.right) / 2}px`,
    top: `${clampedY}px`,
  };
}

function isDesktopRailReorderableApp(appId: string): boolean {
  return appId.toLowerCase() !== APP_STORE_APP_ID;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function reorderedRailAppsForRender(appsToRender: AppRegistryItem[], activeReorder: ActiveRailReorder | null): AppRegistryItem[] {
  if (!activeReorder) {
    return appsToRender;
  }
  const appsById = new Map(appsToRender.map((app) => [app.app_id, app]));
  const reorderedIds = reorderByTargetIndex(activeReorder.appIds, activeReorder.sourceIndex, activeReorder.targetIndex);
  const reorderedApps = reorderedIds.map((appId) => appsById.get(appId)).filter((app): app is AppRegistryItem => Boolean(app));
  const staticApps = appsToRender.filter((app) => !isDesktopRailReorderableApp(app.app_id));
  return [...reorderedApps, ...staticApps];
}

function sidebarRailItemClassName({ isDragging, isDropTarget }: { isDragging: boolean; isDropTarget: boolean }): string {
  return [
    "bs-sidebar__rail-item",
    isDragging ? "is-dragging" : "",
    isDropTarget ? "is-drop-target" : "",
  ]
    .filter(Boolean)
    .join(" ");
}

export function sidebarRailButtonClassName(
  appId: string,
  activeAppId: string | null,
  state: { isDragging?: boolean; isDropTarget?: boolean; isReorderable?: boolean } = {},
): string {
  return [
    "bs-sidebar__rail-button",
    activeAppId === appId ? "is-active" : "",
    state.isReorderable ? "is-reorderable" : "",
    state.isDragging ? "is-dragging" : "",
    state.isDropTarget ? "is-drop-target" : "",
  ]
    .filter(Boolean)
    .join(" ");
}
