import { useEffect } from "react";
import type { ChatThread } from "./api/client";
import { ChatSurface } from "./components/ChatSurface";
import { useChatAppController } from "./hooks/useChatAppController";
import { useChatShellMessages } from "./hooks/useChatShellMessages";
import { useRuntimeEvents } from "./hooks/useRuntimeEvents";
import type { ExternalFileDrop, ExternalMentionDrop } from "./lib/externalInputs";

export function App({
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
      <ChatSurface {...controller.surfaceProps} />
    </main>
  );
}
