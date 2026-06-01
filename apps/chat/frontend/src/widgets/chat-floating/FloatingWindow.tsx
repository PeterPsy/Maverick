import type { ChatThread } from "../../api/client";
import { FloatingChatFrame } from "./FloatingChatFrame";
import type { FloatingChatWindow } from "./floatingState";

export function FloatingWindow({
  className = "",
  onClose,
  onCollapseChange,
  onCreateDraftChat,
  onDock,
  onMarkThreadRead,
  onOverlay,
  onRemoveThread,
  onRenameThread,
  onSelectThread,
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
  className?: string;
  onClose: (windowId: string) => void;
  onCollapseChange: (windowId: string, isCollapsed: boolean) => void;
  onCreateDraftChat: (windowId: string, projectId: string | null) => void;
  onDock: (windowId: string) => void;
  onMarkThreadRead: (thread: ChatThread) => Promise<void>;
  onOverlay?: (windowId: string) => void;
  onRemoveThread: (windowId: string, thread: ChatThread) => Promise<void>;
  onRenameThread: (threadId: string, title: string) => Promise<void>;
  onSelectThread: (windowId: string, threadId: string) => void;
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
      className={className}
      onClose={onClose}
      onCollapseChange={onCollapseChange}
      onCreateDraftChat={onCreateDraftChat}
      onDock={onDock}
      onMarkThreadRead={onMarkThreadRead}
      onOverlay={onOverlay}
      onRemoveThread={onRemoveThread}
      onRenameThread={onRenameThread}
      onSelectThread={onSelectThread}
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
