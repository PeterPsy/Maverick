import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../../styles/main.css";
import { FloatingWindow } from "./FloatingWindow";
import "./styles.css";
import { useFloatingWindows } from "./useFloatingWindows";

function ChatFloatingMount() {
  const floating = useFloatingWindows();
  const hasMultipleWindows = floating.windows.length > 1;

  if (!floating.isWindowStateReady) {
    return null;
  }

  return (
    <div
      className={`chat-floating-widget-stack ${hasMultipleWindows ? "has-multiple-windows" : "has-single-window"}`}
      {...floating.stackHandlers}
      ref={floating.stackRef}
    >
      {floating.windows.map((windowItem) => (
        <FloatingWindow
          key={windowItem.id}
          onClose={floating.closeWindow}
          onCollapseChange={floating.setWindowCollapsed}
          onCreateDraftChat={floating.createDraftChat}
          onMarkThreadRead={floating.markThreadReadIfNeeded}
          onRemoveThread={floating.removeThread}
          onRenameThread={floating.renameThread}
          onSelectThread={floating.selectThread}
          runtimeThreadsError={floating.runtimeThreadsError}
          runtimeThreadsLoaded={floating.runtimeThreadsLoaded}
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
