import type { ChatThread } from "../api/client";
import { debugThreadSync } from "../lib/threadNavigation";

export function postActiveThreadChanged({
  activeThread,
  activeThreadId,
  navigationScope,
  threadId,
}: {
  activeThread: ChatThread | null;
  activeThreadId: string;
  navigationScope: string;
  threadId: string | null;
}) {
  debugThreadSync("app-notify-active-thread", {
    activeThreadId: activeThread?.thread_id || "",
    nextActiveThreadId: activeThreadId,
    navigationScope,
    threadId,
  });
  window.parent?.postMessage(
    {
      type: "maverick.chat.active-thread-changed",
      owner_app_id: "chat",
      active_thread_id: activeThreadId,
      ...(navigationScope ? { navigation_scope: navigationScope } : {}),
    },
    window.location.origin,
  );
}
