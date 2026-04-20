import { type MutableRefObject, useEffect, useMemo, useRef, useState } from "react";
import {
  ChatThread,
  createRuntimeSession,
  createThread,
  getAgentsCommonPrompt,
  getThread,
  getRuntimeSession,
  interruptRuntimeTurn,
  listProviders,
  listRuntimeEvents,
  listThreads,
  ProviderItem,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  selectProvider,
  sendRuntimeTurn,
  updateThread,
} from "./api/client";
import { ChatComposer } from "./components/ChatComposer";
import { ChatHeader } from "./components/ChatHeader";
import { ChatTranscript } from "./components/ChatTranscript";
import { useComposerAttachments } from "./hooks/useComposerAttachments";
import { useRuntimeEvents } from "./hooks/useRuntimeEvents";
import { hasInvalidAttachments } from "./lib/attachments";
import { PendingMessage, QueuedMessage, uploadComposerAttachment } from "./lib/messageState";
import { inferActiveRuntimeTurn, mergeRuntimeEvents } from "./lib/runtimeEvents";
import { latestRuntimeStepLabel } from "./lib/runtimeStepLabels";
import { findThreadByRuntimeSession } from "./lib/threadNavigation";
import { eventsToMessages, firstUserTitle } from "./lib/transcript";

type ShellNavigationMessage = {
  type?: string;
  deleted_thread_id?: string;
  owner_app_id?: string;
  app_id?: string;
  params?: Record<string, string | boolean | null>;
  resource?: string;
};

type RuntimeSessionThreadMetadata = {
  agent_label?: string;
  agent_type_id?: string;
  agent_role_id?: string;
  source_app_id?: string;
  title?: string;
};

export function App() {
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [activeProviderId, setActiveProviderId] = useState("codex");
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThread, setActiveThread] = useState<ChatThread | null>(null);
  const [activeSession, setActiveSession] = useState<RuntimeSession | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [composer, setComposer] = useState("");
  const { addAttachments, attachments, clearAttachments, removeAttachment } = useComposerAttachments();
  const [pendingUserMessages, setPendingUserMessages] = useState<PendingMessage[]>([]);
  const [failedUserMessages, setFailedUserMessages] = useState<PendingMessage[]>([]);
  const [queuedMessages, setQueuedMessages] = useState<QueuedMessage[]>([]);
  const [activeTurn, setActiveTurn] = useState<RuntimeTurn | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);
  const consumedNewChatRequests = useRef<Set<string>>(new Set());
  const consumedLegacyNewChatRequest = useRef(false);

  const messages = useMemo(() => {
    const currentMessages = eventsToMessages(events);
    const confirmedHumanMessages = new Set(currentMessages.filter((message) => message.role === "human").map((message) => message.content.trim()));
    return [
      ...currentMessages,
      ...pendingUserMessages
        .filter((message) => !confirmedHumanMessages.has(message.content.trim()))
        .map((message) => ({
          id: message.clientMessageId,
          role: "human" as const,
          content: message.content,
          createdAt: message.createdAt,
          status: "pending" as const,
          attachments: message.attachments,
        })),
      ...failedUserMessages.map((message) => ({
        id: `${message.clientMessageId}:failed`,
        role: "human" as const,
        content: message.content,
        createdAt: message.createdAt,
        status: "failed" as const,
        attachments: message.attachments,
      })),
    ];
  }, [events, failedUserMessages, pendingUserMessages]);
  const executionMode = activeSession?.effective_mode || "runtime";
  const canStopTurn = activeTurn?.status === "queued" || activeTurn?.status === "active";
  const isRuntimeBusy = canStopTurn;
  const loadingLabel = useMemo(() => {
    if (isHistoryLoading) {
      return "Loading history";
    }
    if (isBootstrapping) {
      return "Loading chat";
    }
    if (!isRuntimeBusy) {
      return "";
    }
    return latestRuntimeStepLabel(events) || "Thinking";
  }, [events, isBootstrapping, isHistoryLoading, isRuntimeBusy]);

  useRuntimeEvents({
    activeTurn,
    runtimeSessionId: activeThread?.runtime_session_id || null,
    setActiveTurn,
    setError,
    setEvents,
    setPendingUserMessages,
  });

  async function loadInitialState() {
    setIsBootstrapping(true);
    try {
      const [providerPayload, threadPayload] = await Promise.all([listProviders(), listThreads()]);
      setProviders(providerPayload.items || [providerPayload.active_provider]);
      setActiveProviderId(providerPayload.active_provider.provider_id);
      setThreads(threadPayload.threads);
      const query = new URLSearchParams(window.location.search);
      const requestedThreadId = query.get("thread_id");
      let firstThread = threadPayload.threads.find((thread) => thread.thread_id === requestedThreadId) || threadPayload.threads[0] || null;
      if (query.get("new_chat") === "1") {
        firstThread = await createChat();
      } else if (requestedThreadId && !firstThread) {
        const thread = await getThread(requestedThreadId);
        firstThread = thread.thread;
        setThreads(thread.threads);
      }
      setActiveThread(firstThread);
      if (firstThread?.runtime_session_id) {
        const [runtimeSession, runtimeEvents] = await Promise.all([
          getRuntimeSession(firstThread.runtime_session_id),
          listRuntimeEvents(firstThread.runtime_session_id),
        ]);
        setActiveSession(runtimeSession);
        setEvents(runtimeEvents.items);
        setActiveTurn(inferActiveRuntimeTurn(runtimeEvents.items, firstThread.runtime_session_id));
      } else {
        setActiveSession(null);
        setActiveTurn(null);
      }
      setPendingUserMessages([]);
      setFailedUserMessages([]);
      setQueuedMessages([]);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load chat.");
    } finally {
      setIsBootstrapping(false);
    }
  }

  useEffect(() => {
    loadInitialState();
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as ShellNavigationMessage;
      if (payload.type === "maverick.app.data-changed" && payload.owner_app_id === "chat" && payload.resource === "threads") {
        void refreshThreadsAfterDataChange(payload.deleted_thread_id || "");
        return;
      }
      if (payload.type !== "maverick.app.navigate" || (payload.app_id && payload.app_id !== "chat")) {
        return;
      }
      void handleNavigationParams(payload.params || {});
    }

    window.addEventListener("message", handleShellMessage);
    window.parent?.postMessage({ type: "maverick.app.ready", app_id: "chat" }, window.location.origin);
    return () => window.removeEventListener("message", handleShellMessage);
  }, [activeThread?.thread_id, threads]);

  async function refreshThreadsAfterDataChange(deletedThreadId: string) {
    try {
      const payload = await listThreads();
      setThreads(payload.threads);
      const activeThreadStillExists = activeThread ? payload.threads.some((thread) => thread.thread_id === activeThread.thread_id) : false;
      if (activeThread && (!activeThreadStillExists || activeThread.thread_id === deletedThreadId)) {
        setActiveThread(null);
        setActiveSession(null);
        setEvents([]);
        setPendingUserMessages([]);
        setFailedUserMessages([]);
        setQueuedMessages([]);
        setActiveTurn(null);
      }
      setError(null);
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "Unable to refresh chats.");
    }
  }

  async function handleSelectProvider(providerId: string) {
    setActiveProviderId(providerId);
    try {
      const payload = await selectProvider(providerId);
      setActiveProviderId(payload.active_provider.provider_id);
      setError(null);
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : "Unable to select provider.");
    }
  }

  async function createChat() {
    const systemPrompt = await loadDefaultSystemPrompt();
    const payload = await createThread("", null, { system_prompt: systemPrompt });
    setThreads(payload.threads);
    setActiveThread(payload.thread);
    setActiveSession(null);
    setEvents([]);
    setPendingUserMessages([]);
    setFailedUserMessages([]);
    setQueuedMessages([]);
    setActiveTurn(null);
    notifyAppDataChanged("chat", "threads");
    return payload.thread;
  }

  async function handleSelectThread(thread: ChatThread) {
    setIsHistoryLoading(true);
    setActiveThread(thread);
    setActiveSession(null);
    setEvents([]);
    setPendingUserMessages([]);
    setFailedUserMessages([]);
    setQueuedMessages([]);
    setActiveTurn(null);
    try {
      if (!thread.runtime_session_id) {
        setError(null);
        return;
      }
      const [runtimeSession, runtimeEvents] = await Promise.all([
        getRuntimeSession(thread.runtime_session_id),
        listRuntimeEvents(thread.runtime_session_id),
      ]);
      setActiveSession(runtimeSession);
      setEvents(runtimeEvents.items);
      setActiveTurn(inferActiveRuntimeTurn(runtimeEvents.items, thread.runtime_session_id));
      setError(null);
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : "Unable to load thread.");
    } finally {
      setIsHistoryLoading(false);
    }
  }

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const requestedThreadId = typeof params.thread_id === "string" ? params.thread_id : null;
    const requestedRuntimeSessionId = typeof params.runtime_session_id === "string" ? params.runtime_session_id : null;
    const runtimeThreadMetadata = runtimeSessionThreadMetadataFromParams(params);
    const shouldCreateChat = params.new_chat === true || params.new_chat === "1";
    if (!requestedThreadId && !requestedRuntimeSessionId && !shouldCreateChat) {
      return;
    }
    if (shouldCreateChat && !consumeNewChatRequest(params, consumedNewChatRequests.current, consumedLegacyNewChatRequest)) {
      return;
    }
    setIsBootstrapping(true);
    try {
      if (requestedRuntimeSessionId) {
        await openRuntimeSessionThread(requestedRuntimeSessionId, runtimeThreadMetadata);
      } else if (shouldCreateChat) {
        await createChat();
      } else if (requestedThreadId) {
        await openThreadById(requestedThreadId);
      }
      setError(null);
    } catch (navigationError) {
      setError(navigationError instanceof Error ? navigationError.message : "Unable to open chat.");
    } finally {
      setIsBootstrapping(false);
    }
  }

  async function openRuntimeSessionThread(runtimeSessionId: string, metadata: RuntimeSessionThreadMetadata) {
    const existingThread = findThreadByRuntimeSession(threads, runtimeSessionId);
    if (existingThread) {
      await handleSelectThread(existingThread);
      return;
    }
    setIsHistoryLoading(true);
    try {
      const [runtimeSession, payload] = await Promise.all([getRuntimeSession(runtimeSessionId), createThread(runtimeSessionId, null, metadata)]);
      setThreads(payload.threads);
      setActiveThread(payload.thread);
      setActiveSession(runtimeSession);
      const runtimeEvents = await listRuntimeEvents(runtimeSessionId);
      setEvents(runtimeEvents.items);
      setPendingUserMessages([]);
      setFailedUserMessages([]);
      setQueuedMessages([]);
      setActiveTurn(inferActiveRuntimeTurn(runtimeEvents.items, runtimeSessionId));
      notifyAppDataChanged("chat", "threads");
    } finally {
      setIsHistoryLoading(false);
    }
  }

  async function openThreadById(threadId: string) {
    if (activeThread?.thread_id === threadId && (!activeThread.runtime_session_id || activeSession || events.length > 0)) {
      return;
    }
    const existingThread = threads.find((thread) => thread.thread_id === threadId);
    if (existingThread) {
      await handleSelectThread(existingThread);
      return;
    }
    const payload = await getThread(threadId);
    setThreads(payload.threads);
    await handleSelectThread(payload.thread);
  }

  async function handleSend() {
    const input = composer.trim();
    if ((!input && !attachments.length) || hasInvalidAttachments(attachments)) {
      return;
    }
    const clientMessageId = crypto.randomUUID();
    setComposerError(null);
    let messageAttachments;
    try {
      messageAttachments = await Promise.all(attachments.map(uploadComposerAttachment));
    } catch (uploadError) {
      setComposerError(uploadError instanceof Error ? uploadError.message : "Unable to upload attachments.");
      return;
    }
    setComposer("");
    clearAttachments();
    if (isRuntimeBusy || isSending) {
      setQueuedMessages((current) => [...current, { clientMessageId, content: input, attachments: messageAttachments }]);
      return;
    }
    await submitMessage({ clientMessageId, content: input, attachments: messageAttachments });
  }

  async function submitMessage(message: QueuedMessage) {
    setPendingUserMessages((current) => [
      ...current,
      {
        clientMessageId: message.clientMessageId,
        content: message.content,
        createdAt: new Date().toISOString(),
        attachments: message.attachments,
      },
    ]);
    setFailedUserMessages((current) => current.filter((item) => item.clientMessageId !== message.clientMessageId));
    setIsSending(true);
    setError(null);
    try {
      let thread = activeThread;
      if (!thread) {
        thread = await createChat();
      } else if (!threads.some((item) => item.thread_id === thread?.thread_id)) {
        throw new Error("This chat no longer exists.");
      }
      if (!thread.runtime_session_id) {
        const session = await createRuntimeSession({
          system_prompt: thread.system_prompt,
          source_app_id: "chat",
        });
        const updated = await updateThread({ thread_id: thread.thread_id, runtime_session_id: session.session_id });
        thread = updated.thread;
        setActiveThread(thread);
        setActiveSession(session);
        setThreads(updated.threads);
      }
      const response = await sendRuntimeTurn(thread.runtime_session_id, message.content, message.clientMessageId, message.attachments);
      setActiveSession(response.session);
      setActiveTurn(response.turn);
      setEvents((current) => mergeRuntimeEvents(current, response.events));
      if (response.turn.status !== "queued" && response.turn.status !== "active") {
        setPendingUserMessages((current) => current.filter((item) => item.clientMessageId !== message.clientMessageId));
      }
      if (events.length === 0 && thread.title === "New chat") {
        const updated = await updateThread({ thread_id: thread.thread_id, title: firstUserTitle(message.content) });
        setActiveThread(updated.thread);
        setThreads(updated.threads);
      }
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : "Unable to send message.");
      setComposer(message.content);
      setPendingUserMessages((current) => current.filter((item) => item.clientMessageId !== message.clientMessageId));
      setFailedUserMessages((current) => [
        ...current,
        {
          clientMessageId: message.clientMessageId,
          content: message.content,
          createdAt: new Date().toISOString(),
          attachments: message.attachments,
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  useEffect(() => {
    if (isRuntimeBusy || isSending || queuedMessages.length === 0) {
      return;
    }
    const [nextMessage, ...remainingMessages] = queuedMessages;
    setQueuedMessages(remainingMessages);
    void submitMessage(nextMessage);
  }, [isRuntimeBusy, isSending, queuedMessages]);

  function handleAddAttachments(files: File[]) {
    addAttachments(files);
    setComposerError(null);
  }

  async function handleStopTurn() {
    if (!activeTurn || !canStopTurn) {
      return;
    }
    try {
      const response = await interruptRuntimeTurn(activeTurn.turn_id);
      setActiveTurn(response.turn);
      if (response.event) {
        setEvents((current) => mergeRuntimeEvents(current, [response.event as RuntimeEvent]));
      }
      setError(null);
    } catch (stopError) {
      setError(stopError instanceof Error ? stopError.message : "Unable to stop runtime turn.");
    }
  }

  return (
    <main className="chatapp-root">
      <section className="chatapp-chat-panel">
        <ChatHeader
          activeProviderId={activeProviderId}
          disabled={isBootstrapping || isSending}
          executionMode={executionMode}
          onSelectProvider={handleSelectProvider}
          providers={providers}
        />

        <div className="chatapp-chat-workspace">
          <div className="chatapp-chat-main">
            <ChatTranscript
              activeThread={activeThread}
              error={error}
              isLoading={isRuntimeBusy || isBootstrapping || isHistoryLoading}
              loadingLabel={loadingLabel}
              messages={messages}
            />
            <ChatComposer
              attachments={attachments}
              canStopTurn={canStopTurn}
              disabled={isBootstrapping || isHistoryLoading}
              error={composerError}
              isSending={isRuntimeBusy || isSending}
              onAddAttachments={handleAddAttachments}
              onChange={setComposer}
              onRemoveAttachment={removeAttachment}
              onStopTurn={handleStopTurn}
              onSubmit={handleSend}
              queuedCount={queuedMessages.length}
              queuedPreview={queuedMessages[0]?.content || null}
              value={composer}
            />
          </div>
        </div>
      </section>
    </main>
  );
}

function runtimeSessionThreadMetadataFromParams(params: Record<string, string | boolean | null>): RuntimeSessionThreadMetadata {
  const agentLabel = scalarString(params.agent_label);
  const threadTitle = scalarString(params.thread_title) || agentLabel;
  return {
    agent_label: agentLabel,
    agent_type_id: scalarString(params.agent_type_id),
    agent_role_id: scalarString(params.agent_role_id),
    source_app_id: scalarString(params.source_app_id) || "agents",
    title: threadTitle,
  };
}

function consumeNewChatRequest(
  params: Record<string, string | boolean | null>,
  consumedRequestIds: Set<string>,
  consumedLegacyRequest: MutableRefObject<boolean>,
): boolean {
  const requestId = scalarString(params.new_chat_request_id);
  if (!requestId) {
    if (consumedLegacyRequest.current) {
      return false;
    }
    consumedLegacyRequest.current = true;
    return true;
  }
  if (consumedRequestIds.has(requestId)) {
    return false;
  }
  consumedRequestIds.add(requestId);
  return true;
}

async function loadDefaultSystemPrompt(): Promise<string> {
  try {
    return await getAgentsCommonPrompt();
  } catch {
    return "";
  }
}

function scalarString(value: string | boolean | null | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

function notifyAppDataChanged(ownerAppId: string, resource: string) {
  window.parent?.postMessage(
    {
      type: "maverick.app.data-changed",
      owner_app_id: ownerAppId,
      resource,
    },
    window.location.origin,
  );
}
