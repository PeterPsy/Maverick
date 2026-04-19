import { useEffect, useMemo, useState } from "react";
import {
  ChatThread,
  createRuntimeSession,
  createThread,
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
import { hasInvalidAttachments } from "./lib/attachments";
import { PendingMessage, QueuedMessage, uploadComposerAttachment } from "./lib/messageState";
import { eventsToMessages, firstUserTitle } from "./lib/transcript";

type ShellNavigationMessage = {
  type?: string;
  app_id?: string;
  params?: Record<string, string | boolean | null>;
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
  const [queuedMessages, setQueuedMessages] = useState<QueuedMessage[]>([]);
  const [activeTurn, setActiveTurn] = useState<RuntimeTurn | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [composerError, setComposerError] = useState<string | null>(null);

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
    ];
  }, [events, pendingUserMessages]);
  const activeProvider = providers.find((provider) => provider.provider_id === activeProviderId) || providers[0] || null;
  const runtimeStatus = activeTurn?.status || (isSending ? "running" : isBootstrapping ? "loading" : "ready");
  const executionMode = activeSession?.effective_mode || "runtime";
  const canStopTurn = activeTurn?.status === "queued" || activeTurn?.status === "active";
  const isRuntimeBusy = isSending || canStopTurn;

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
      } else {
        setActiveSession(null);
      }
      setPendingUserMessages([]);
      setQueuedMessages([]);
      setActiveTurn(null);
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
      if (payload.type !== "maverick.app.navigate" || (payload.app_id && payload.app_id !== "chat")) {
        return;
      }
      void handleNavigationParams(payload.params || {});
    }

    window.addEventListener("message", handleShellMessage);
    window.parent?.postMessage({ type: "maverick.app.ready", app_id: "chat" }, window.location.origin);
    return () => window.removeEventListener("message", handleShellMessage);
  }, [activeThread?.thread_id, threads]);

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
    const session = await createRuntimeSession();
    const payload = await createThread(session.session_id);
    setThreads(payload.threads);
    setActiveThread(payload.thread);
    setActiveSession(session);
    setEvents([]);
    setPendingUserMessages([]);
    setQueuedMessages([]);
    setActiveTurn(null);
    return payload.thread;
  }

  async function handleCreateChat() {
    setIsBootstrapping(true);
    try {
      await createChat();
      setError(null);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Unable to create chat.");
    } finally {
      setIsBootstrapping(false);
    }
  }

  async function handleSelectThread(thread: ChatThread) {
    setActiveThread(thread);
    setActiveSession(null);
    setEvents([]);
    setPendingUserMessages([]);
    setQueuedMessages([]);
    setActiveTurn(null);
    if (!thread.runtime_session_id) {
      return;
    }
    try {
      const [runtimeSession, runtimeEvents] = await Promise.all([
        getRuntimeSession(thread.runtime_session_id),
        listRuntimeEvents(thread.runtime_session_id),
      ]);
      setActiveSession(runtimeSession);
      setEvents(runtimeEvents.items);
      setError(null);
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : "Unable to load thread.");
    }
  }

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const requestedThreadId = typeof params.thread_id === "string" ? params.thread_id : null;
    const shouldCreateChat = params.new_chat === true || params.new_chat === "1";
    if (!requestedThreadId && !shouldCreateChat) {
      return;
    }
    setIsBootstrapping(true);
    try {
      if (shouldCreateChat) {
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
    if (isRuntimeBusy) {
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
    setIsSending(true);
    setError(null);
    try {
      let thread = activeThread;
      if (!thread) {
        thread = await createChat();
      }
      if (!thread.runtime_session_id) {
        const session = await createRuntimeSession();
        const updated = await updateThread({ thread_id: thread.thread_id, runtime_session_id: session.session_id });
        thread = updated.thread;
        setActiveThread(thread);
        setActiveSession(session);
        setThreads(updated.threads);
      }
      const response = await sendRuntimeTurn(thread.runtime_session_id, message.content, message.clientMessageId, message.attachments);
      setActiveSession(response.session);
      setActiveTurn(response.turn);
      setEvents((current) => [...current, ...response.events]);
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
    } finally {
      setIsSending(false);
    }
  }

  useEffect(() => {
    if (isRuntimeBusy || queuedMessages.length === 0) {
      return;
    }
    const [nextMessage, ...remainingMessages] = queuedMessages;
    setQueuedMessages(remainingMessages);
    void submitMessage(nextMessage);
  }, [isRuntimeBusy, queuedMessages]);

  useEffect(() => {
    if (!activeThread?.runtime_session_id || !activeTurn || !["queued", "active"].includes(activeTurn.status)) {
      return;
    }
    const interval = window.setInterval(async () => {
      try {
        const runtimeEvents = await listRuntimeEvents(activeThread.runtime_session_id);
        setEvents(runtimeEvents.items);
        const matchingMessages = eventsToMessages(runtimeEvents.items);
        const hasConfirmedMessage = matchingMessages.some((message) => message.id === activeTurn.turn_id || message.id.includes(activeTurn.turn_id));
        const terminalEvent = runtimeEvents.items.find((event) =>
          event.turn_id === activeTurn.turn_id && ["runtime.turn.completed", "runtime.turn.failed", "runtime.turn.cancelled"].includes(event.event_type),
        );
        if (terminalEvent) {
          setActiveTurn((current) => (current?.turn_id === activeTurn.turn_id ? { ...current, status: terminalEvent.event_type.split(".").at(-1) || current.status } : current));
          setPendingUserMessages((current) => current.filter((item) => !matchingMessages.some((message) => message.id === item.clientMessageId)));
        } else if (hasConfirmedMessage) {
          setPendingUserMessages((current) => current.filter((item) => !matchingMessages.some((message) => message.id === item.clientMessageId)));
        }
      } catch (pollError) {
        setError(pollError instanceof Error ? pollError.message : "Unable to refresh runtime events.");
      }
    }, 900);
    return () => window.clearInterval(interval);
  }, [activeThread?.runtime_session_id, activeTurn]);

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
        setEvents((current) => [...current, response.event as RuntimeEvent]);
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
          activeProvider={activeProvider}
          activeProviderId={activeProviderId}
          disabled={isBootstrapping || isSending}
          executionMode={executionMode}
          onCreateChat={handleCreateChat}
          onSelectProvider={handleSelectProvider}
          providers={providers}
          runtimeStatus={runtimeStatus}
          title={activeThread?.title || "New chat"}
        />

        <div className="chatapp-chat-workspace">
          <div className="chatapp-chat-main">
            <ChatTranscript
              error={error}
              isLoading={isRuntimeBusy || isBootstrapping}
              loadingLabel={isRuntimeBusy ? `${activeProvider?.label || "Provider"} sta lavorando` : "Caricamento chat"}
              messages={messages}
            />
            <ChatComposer
              attachments={attachments}
              canStopTurn={canStopTurn}
              disabled={isBootstrapping}
              error={composerError}
              isSending={isRuntimeBusy}
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
