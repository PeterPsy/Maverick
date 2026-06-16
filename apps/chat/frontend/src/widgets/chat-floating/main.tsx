import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../../styles/main.css";
import { applyInitialMaverickTheme, listenForMaverickThemeMessages } from "../../lib/shellTheme";
import { FloatingWindow } from "./FloatingWindow";
import type { FloatingChatWindow } from "./floatingState";
import "./styles.css";
import { useFloatingWindows } from "./useFloatingWindows";

applyInitialMaverickTheme();
listenForMaverickThemeMessages();

function ChatFloatingMount() {
  const floating = useFloatingWindows();
  const hasMultipleWindows = floating.windows.length > 1;

  if (!floating.isWindowStateReady) {
    return null;
  }

  const isOverlayMode = floating.hostMode === "overlay";
  const visibleWindows = isOverlayMode
    ? floating.windows
    : singleFloatingWindow(floating.windows, floating.hostNavigationScope, floating.hostThreadId);

  return (
    <div
      className={`chat-floating-widget-stack ${hasMultipleWindows && isOverlayMode ? "has-multiple-windows" : "has-single-window"} is-${floating.hostMode}`}
      {...floating.stackHandlers}
      ref={floating.stackRef}
    >
      {visibleWindows.map((windowItem) => (
        <FloatingWindow
          className={
            floating.hostMode === "mobile-fullscreen"
              ? "chat-floating-widget-shell--mobile-fullscreen"
              : floating.hostMode === "fixed-right"
                ? "chat-floating-widget-shell--dock"
                : ""
          }
          key={windowItem.id}
          onClose={isOverlayMode ? floating.closeWindow : floating.closeDock}
          onCollapseChange={floating.setWindowCollapsed}
          onCreateDraftChat={floating.createDraftChat}
          onDock={floating.dockWindow}
          onMarkThreadRead={floating.markThreadReadIfNeeded}
          onOverlay={floating.closeDock}
          onRemoveThread={floating.removeThread}
          onRenameThread={floating.renameThread}
          onSelectThread={floating.selectThread}
          runtimeThreadsError={floating.runtimeThreadsError}
          runtimeThreadsLoaded={floating.runtimeThreadsLoaded}
          showCollapse={isOverlayMode}
          showClose={isOverlayMode || floating.hostMode !== "mobile-fullscreen"}
          showDock={isOverlayMode}
          showLauncher={isOverlayMode}
          showOverlay={!isOverlayMode && floating.hostMode !== "mobile-fullscreen"}
          threads={floating.threads}
          windowItem={windowItem}
        />
      ))}
    </div>
  );
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <ChatFloatingMount />
  </StrictMode>,
);

function singleFloatingWindow(windows: FloatingChatWindow[], navigationScope: string, threadId: string): FloatingChatWindow[] {
  const windowItem =
    (navigationScope ? windows.find((windowItem) => windowItem.id === navigationScope) : null) ||
    (threadId ? windows.find((windowItem) => windowItem.threadId === threadId && !windowItem.isDraft) : null) ||
    [...windows].reverse().find((windowItem) => !windowItem.isCollapsed) ||
    windows[0] ||
    null;
  return windowItem ? [windowItem] : [];
}
