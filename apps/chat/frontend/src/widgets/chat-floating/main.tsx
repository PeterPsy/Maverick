import { StrictMode } from "react";
import { listenForShellReferenceDrops } from "../../lib/shellReferenceDrop";
import { createRoot } from "react-dom/client";
import "../../styles/main.css";
import { applyInitialLoopinoTheme, listenForLoopinoThemeMessages } from "../../lib/shellTheme";
import { FloatingWindow } from "./FloatingWindow";
import type { FloatingChatWindow } from "./floatingState";
import "./styles.css";
import "./controls.css";
import { useFloatingWindows } from "./useFloatingWindows";

applyInitialLoopinoTheme();
listenForLoopinoThemeMessages();
listenForShellReferenceDrops();

function ChatFloatingMount() {
  const floating = useFloatingWindows();
  const hasMultipleWindows = floating.windows.length > 1;

  if (!floating.isWindowStateReady) {
    return null;
  }

  const isOverlayMode = floating.hostMode === "overlay";
  const selectedWindow = singleFloatingWindow(floating.windows, floating.hostNavigationScope)[0];

  return (
    <div
      className={`chat-floating-widget-stack ${hasMultipleWindows && isOverlayMode ? "has-multiple-windows" : "has-single-window"} is-${floating.hostMode}`}
      ref={floating.stackRef}
    >
      {floating.windows.map((windowItem) => {
        const active = isOverlayMode || windowItem.id === selectedWindow?.id;
        const displayedWindow = !isOverlayMode && active ? { ...windowItem, isCollapsed: false } : windowItem;
        return <div key={windowItem.id} data-window-id={windowItem.id} className="chat-floating-window-slot" hidden={!active} inert={!active}>
        <FloatingWindow
          className={
            floating.hostMode === "mobile-fullscreen"
              ? "chat-floating-widget-shell--mobile-fullscreen"
              : floating.hostMode === "fixed-right"
                ? "chat-floating-widget-shell--dock"
                : ""
          }
          activeAppContext={floating.activeAppContext}
          isActive={active}
          onClose={(windowId) => { floating.closeWindow(windowId); if (!isOverlayMode) floating.closeDock(); }}
          onCollapseChange={floating.setWindowCollapsed}
          onCreateDraftChat={floating.createDraftChat}
          onDock={floating.dockWindow}
          onMarkThreadRead={floating.markThreadReadIfNeeded}
          onOverlay={floating.closeDock}
          onSelectThread={floating.selectThread}
          onThreadsDeleted={floating.resetDeletedThreads}
          runtimeThreadsError={floating.runtimeThreadsError}
          runtimeThreadsLoaded={floating.runtimeThreadsLoaded}
          showCollapse={isOverlayMode}
          showClose={isOverlayMode || floating.hostMode !== "mobile-fullscreen"}
          showDock={isOverlayMode}
          showLauncher={isOverlayMode}
          showOverlay={!isOverlayMode && floating.hostMode !== "mobile-fullscreen"}
          threads={floating.threads}
          windowItem={displayedWindow}
        />
        </div>;
      })}
      {isOverlayMode && hasMultipleWindows ? <nav className="chat-floating-stack-navigation" aria-label="Chat windows">
        <button type="button" aria-label="Previous chat windows" onClick={() => floating.stackRef.current?.scrollBy({ left: -412, behavior: "smooth" })}>←</button>
        <span>{floating.windows.length} chats</span>
        <button type="button" aria-label="Next chat windows" onClick={() => floating.stackRef.current?.scrollBy({ left: 412, behavior: "smooth" })}>→</button>
      </nav> : null}
    </div>
  );
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <ChatFloatingMount />
  </StrictMode>,
);

function singleFloatingWindow(windows: FloatingChatWindow[], navigationScope: string): FloatingChatWindow[] {
  const windowItem =
    (navigationScope ? windows.find((windowItem) => windowItem.id === navigationScope) : null) ||
    [...windows].reverse().find((windowItem) => !windowItem.isCollapsed) ||
    windows[0] ||
    null;
  return windowItem ? [windowItem] : [];
}
