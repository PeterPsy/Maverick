import type { ActiveAppContext } from "../../lib/activeAppContext";
import type { ChatThread } from "../../api/client";
import { FloatingChatFrame } from "./FloatingChatFrame";
import type { FloatingChatWindow } from "./floatingState";

export function FloatingWindow({
  activeAppContext = null,
  className = "",
  isActive = true,
  onClose,
  onCollapseChange,
  onCreateDraftChat,
  onDock,
  onMarkThreadRead,
  onOverlay,
  onSelectThread,
  onThreadsDeleted,
  runtimeThreadsError,
  runtimeThreadsLoaded,
  showCollapse = true,
  showClose = true,
  showDock = true,
  showLauncher = true,
  showOverlay = false,
  threads,
  windowItem,
}: {
  activeAppContext?: ActiveAppContext | null;
  className?: string;
  isActive?: boolean;
  onClose: (windowId: string) => void;
  onCollapseChange: (windowId: string, isCollapsed: boolean) => void;
  onCreateDraftChat: (windowId: string, projectId: string | null) => void;
  onDock: (windowId: string) => void;
  onMarkThreadRead: (thread: ChatThread) => Promise<void>;
  onOverlay?: (windowId: string) => void;
  onSelectThread: (windowId: string, threadId: string, thread?: ChatThread) => void;
  onThreadsDeleted: (threadIds: string[], projectId?: string) => void;
  runtimeThreadsError: string | null;
  runtimeThreadsLoaded: boolean;
  showCollapse?: boolean;
  showClose?: boolean;
  showDock?: boolean;
  showLauncher?: boolean;
  showOverlay?: boolean;
  threads: ChatThread[];
  windowItem: FloatingChatWindow;
}) {
  return (
    <FloatingChatFrame
      activeAppContext={activeAppContext}
      className={className}
      isActive={isActive}
      onClose={onClose}
      onCollapseChange={onCollapseChange}
      onCreateDraftChat={onCreateDraftChat}
      onDock={onDock}
      onMarkThreadRead={onMarkThreadRead}
      onOverlay={onOverlay}
      onSelectThread={onSelectThread}
      onThreadsDeleted={onThreadsDeleted}
      runtimeThreadsError={runtimeThreadsError}
      runtimeThreadsLoaded={runtimeThreadsLoaded}
      showCollapse={showCollapse}
      showClose={showClose}
      showDock={showDock}
      showLauncher={showLauncher}
      showOverlay={showOverlay}
      threads={threads}
      windowItem={windowItem}
    />
  );
}
