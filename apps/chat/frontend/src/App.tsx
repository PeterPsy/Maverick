import { useEffect, useMemo, useState } from "react";
import {
  ChatThread,
  createRuntimeSession,
  createThread,
  listProviders,
  listRuntimeEvents,
  listThreads,
  ProviderItem,
  RuntimeEvent,
  selectProvider,
  sendRuntimeTurn,
  updateThread,
} from "./api/client";
import { ChatComposer } from "./components/ChatComposer";
import { ChatTranscript } from "./components/ChatTranscript";
import { ProviderSelector } from "./components/ProviderSelector";
import { eventsToMessages, firstUserTitle } from "./lib/transcript";

export function App() {
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [activeProviderId, setActiveProviderId] = useState("codex");
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThread, setActiveThread] = useState<ChatThread | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [composer, setComposer] = useState("");
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const messages = useMemo(() => eventsToMessages(events), [events]);
  const activeProvider = providers.find((provider) => provider.provider_id === activeProviderId) || providers[0] || null;

  async function loadInitialState() {
    setIsBootstrapping(true);
    try {
      const [providerPayload, threadPayload] = await Promise.all([listProviders(), listThreads()]);
      setProviders(providerPayload.items || [providerPayload.active_provider]);
      setActiveProviderId(providerPayload.active_provider.provider_id);
      setThreads(threadPayload.threads);
      const firstThread = threadPayload.threads[0] || null;
      setActiveThread(firstThread);
      if (firstThread?.runtime_session_id) {
        const runtimeEvents = await listRuntimeEvents(firstThread.runtime_session_id);
        setEvents(runtimeEvents.items);
      }
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
    setEvents([]);
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
    setEvents([]);
    if (!thread.runtime_session_id) {
      return;
    }
    try {
      const runtimeEvents = await listRuntimeEvents(thread.runtime_session_id);
      setEvents(runtimeEvents.items);
      setError(null);
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : "Unable to load thread.");
    }
  }

  async function handleSend() {
    const input = composer.trim();
    if (!input || isSending) {
      return;
    }
    setComposer("");
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
        setThreads(updated.threads);
      }
      const response = await sendRuntimeTurn(thread.runtime_session_id, input);
      setEvents((current) => [...current, ...response.events]);
      if (messages.length === 0 && thread.title === "New chat") {
        const updated = await updateThread({ thread_id: thread.thread_id, title: firstUserTitle(input) });
        setActiveThread(updated.thread);
        setThreads(updated.threads);
      }
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : "Unable to send message.");
      setComposer(input);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <main className="chatapp-root">
      <section className="chatapp-chat-panel">
        <header className="chat-ui-surface chatapp-chat-panel__meta">
          <div className="chatapp-chat-panel__meta-copy">
            <span className="chatapp-chat-panel__meta-name">{activeThread?.title || "New chat"}</span>
            <span className="chatapp-chat-panel__meta-detail">{activeProvider?.label || "Codex"}</span>
            <span className="chatapp-chat-panel__meta-separator" aria-hidden="true">
              ·
            </span>
            <span className="chatapp-chat-panel__meta-detail">
              {isSending ? "working" : isBootstrapping ? "loading" : "ready"}
            </span>
          </div>
          <div className="chatapp-chat-panel__meta-actions">
            <button
              className="chatapp-chat-panel__icon-action"
              disabled={isBootstrapping || isSending}
              onClick={handleCreateChat}
              title="Nuova chat"
              type="button"
            >
              +
            </button>
            <ProviderSelector
              activeProviderId={activeProviderId}
              disabled={isSending}
              onSelect={handleSelectProvider}
              providers={providers}
            />
            <div className="chatapp-badge-row">
              <span className="chat-ui-badge chat-ui-badge--success">connected</span>
              <span className="chat-ui-badge chat-ui-badge--secondary">sandbox</span>
            </div>
          </div>
        </header>

        <div className="chatapp-chat-workspace">
          <div className="chatapp-chat-main">
            <ChatTranscript error={error} isLoading={isSending || isBootstrapping} messages={messages} />
            <ChatComposer disabled={isBootstrapping} isSending={isSending} onChange={setComposer} onSubmit={handleSend} value={composer} />
          </div>
        </div>
      </section>
    </main>
  );
}
