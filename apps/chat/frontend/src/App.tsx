import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { isExactMaverickParentMessage } from "@maverick/pwa-cache";
import type { ChatThread } from "./api/client";
import { ChatSurface } from "./components/ChatSurface";
import type { ChatSurfaceProps } from "./components/ChatSurface";
import { useChatAppController } from "./hooks/useChatAppController";
import { useChatShellMessages } from "./hooks/useChatShellMessages";
import { useRuntimeEvents } from "./hooks/useRuntimeEvents";
import type { ExternalFileDrop, ExternalMentionDrop } from "./lib/externalInputs";
import { normalizeChatRouteParams, type ShellRouteParams } from "./lib/shellNavigation";

export function ServerChatApp({
  enablePageCapture = false,
  externalFileDrop = null,
  externalMentionDrop = null,
  navigationScope = "",
  newChatProjectId = null,
  newChatRequestId = null,
  runtimeThreads = null,
  runtimeThreadsError = null,
  runtimeThreadsLoaded = false,
  threadId = null,
  renderSurface,
}: {
  enablePageCapture?: boolean;
  externalFileDrop?: ExternalFileDrop | null;
  externalMentionDrop?: ExternalMentionDrop | null;
  navigationScope?: string;
  newChatProjectId?: string | null;
  newChatRequestId?: string | null;
  runtimeThreads?: ChatThread[] | null;
  runtimeThreadsError?: string | null;
  runtimeThreadsLoaded?: boolean;
  threadId?: string | null;
  renderSurface?: (props: ChatSurfaceProps) => ReactNode;
} = {}) {
  const controller = useChatAppController({
    enablePageCapture,
    externalFileDrop,
    externalMentionDrop,
    navigationScope,
    newChatProjectId,
    newChatRequestId,
    runtimeThreads,
    runtimeThreadsError,
    runtimeThreadsLoaded,
    threadId,
  });

  useRuntimeEvents(controller.runtimeEvents);

  useEffect(() => {
    void controller.loadInitialState();
  }, [controller.loadInitialState]);

  useChatShellMessages(controller.shellMessages);

  return (
    <main className="chatapp-root" {...controller.rootProps}>
      {renderSurface ? renderSurface(controller.surfaceProps) : <ChatSurface {...controller.surfaceProps} />}
    </main>
  );
}

export function App(props: Parameters<typeof ServerChatApp>[0] = {}) {
  if (!props.navigationScope) return <ChatAppRoutes {...props} />;
  return <ServerChatApp {...props} />;
}

const ScheduledChats = lazy(() => import("./components/scheduled/ScheduledChats"));

function ChatAppRoutes(props: Parameters<typeof ServerChatApp>[0] = {}) {
  const [page, setPage] = useState(() => new URLSearchParams(window.location.search).get("app_page") || "");
  const [route, setRoute] = useState<ShellRouteParams>({});
  useEffect(() => {
    function navigate(event: MessageEvent) {
      if (!isExactMaverickParentMessage(event) || event.data?.type !== "maverick.app.navigate"
        || event.data.app_id && event.data.app_id !== "chat" || event.data.navigation_scope) return;
      const next = event.data.params?.app_page;
      setPage(typeof next === "string" ? next : "");
      setRoute(normalizeChatRouteParams(event.data.params || {}));
    }
    window.addEventListener("message", navigate);
    return () => window.removeEventListener("message", navigate);
  }, []);
  if (page === "scheduled" || /^scheduled\/[A-Za-z0-9_-]{1,80}$/.test(page)) {
    return <Suspense fallback={<main className="chatapp-root"><p role="status">Loading scheduled chats…</p></main>}>
      <ScheduledChats chatId={page.split("/")[1] || null} onNavigate={setPage} />
    </Suspense>;
  }
  const routedThread = typeof route.thread_id === "string" ? route.thread_id : typeof route.runtime_session_id === "string" ? route.runtime_session_id : null;
  return <ServerChatApp {...props} threadId={routedThread || props.threadId}
    newChatRequestId={typeof route.new_chat_request_id === "string" ? route.new_chat_request_id : props.newChatRequestId}
    newChatProjectId={typeof route.project_id === "string" ? route.project_id : props.newChatProjectId} />;
}
