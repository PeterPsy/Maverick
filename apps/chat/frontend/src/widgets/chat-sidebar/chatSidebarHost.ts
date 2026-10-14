import type { ChatThread } from "../../api/client";

/** A conversation browser embedded in another Chat surface. */
export type ChatSidebarHost = {
  activeThreadId: string;
  initialThreads: ChatThread[];
  isMobileLayout: boolean;
  onCreateChat: (projectId: string | null) => void;
  onSelectThread: (thread: ChatThread) => void;
  onThreadsDeleted: (threadIds: string[], projectId?: string) => void;
};
