/**
 * @vitest-environment happy-dom
 */
import { act, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type AppReference, type ChatThread, type RuntimeEvent, type RuntimeSession, type RuntimeTurn } from "../api/client";
import type { PendingMessage, QueuedMessage } from "../lib/messageState";
import { useChatNavigation } from "./useChatNavigation";
import type { DraftChat } from "./useMessageSubmission";

const apiMocks = vi.hoisted(() => ({
  createThread: vi.fn(),
  getRuntimeThread: vi.fn(),
  isRuntimeSessionUnavailableError: vi.fn(() => false),
}));

const transcriptMocks = vi.hoisted(() => ({
  handleUnavailableRuntimeSession: vi.fn(),
  setActiveRuntimeSessionId: vi.fn(),
}));

const shellMocks = vi.hoisted(() => ({
  openChatRootRouteInShell: vi.fn(),
  openChatThreadRouteInShell: vi.fn(),
}));

const catalogMocks = vi.hoisted(() => ({ threadsLoaded: true }));

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    createThread: apiMocks.createThread,
    getRuntimeThread: apiMocks.getRuntimeThread,
    isRuntimeSessionUnavailableError: apiMocks.isRuntimeSessionUnavailableError,
  };
});

vi.mock("./useRuntimeThreadCatalog", () => ({
  useRuntimeThreadCatalog: () => ({ threadsLoaded: catalogMocks.threadsLoaded }),
}));

vi.mock("./useRuntimeTranscriptCache", () => ({
  useRuntimeTranscriptCache: () => ({
    cachedActiveTurnForThread: () => null,
    cachedTranscriptForThread: () => null,
    handleUnavailableRuntimeSession: transcriptMocks.handleUnavailableRuntimeSession,
    setActiveRuntimeSessionId: transcriptMocks.setActiveRuntimeSessionId,
  }),
}));

vi.mock("../lib/activeAppContext", () => ({
  loadDefaultSystemPrompt: vi.fn(async () => ""),
}));

vi.mock("../lib/queuedMessages", () => ({
  transferQueuedMessages: vi.fn(),
  queueMemoryKey: (navigationScope: string, conversationKey: string) => `${navigationScope}:${conversationKey}`,
  readPendingMessages: vi.fn(() => []),
  readQueuedMessages: vi.fn(() => []),
  readRecoverableQueuedMessages: vi.fn(() => []),
}));

vi.mock("../lib/shellNavigation", async (importOriginal) => ({
  ...await importOriginal<typeof import("../lib/shellNavigation")>(),
  openChatRootRouteInShell: shellMocks.openChatRootRouteInShell,
  openChatThreadRouteInShell: shellMocks.openChatThreadRouteInShell,
}));

vi.mock("../lib/threadNavigation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/threadNavigation")>();
  return {
    ...actual,
    debugThreadSync: vi.fn(),
  };
});

type ProbeState = {
  activeThread: ChatThread | null;
  draftChat: DraftChat | null;
  error: string | null;
  isBootstrapping: boolean;
  targetConversationResolved: boolean;
  threads: ChatThread[];
};

function thread(overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    thread_id: "thread-1",
    runtime_session_id: "session-1",
    title: "Thread",
    agent_label: "chat",
    agent_type_id: "",
    agent_role_id: "",
    source_app_id: "chat",
    project_id: null,
    archived: false,
    availability: "free",
    created_at: "2026-07-08T12:00:00.000Z",
    updated_at: "2026-07-08T12:00:00.000Z",
    ...overrides,
  };
}

function NavigationProbe({
  initialThreads = [],
  onNavigationReady,
  onState,
  threadId,
}: {
  initialThreads?: ChatThread[];
  onNavigationReady?: (navigation: ReturnType<typeof useChatNavigation>) => void;
  onState: (state: ProbeState) => void;
  threadId: string | null;
}) {
  const [activeInterAgentGraphRunId, setActiveInterAgentGraphRunId] = useState<string | null>(null);
  const [activeSession, setActiveSession] = useState<RuntimeSession | null>(null);
  const [activeThread, setActiveThread] = useState<ChatThread | null>(null);
  const [activeTurn, setActiveTurn] = useState<RuntimeTurn | null>(null);
  const [composer, setComposer] = useState("");
  const [draftChat, setDraftChat] = useState<DraftChat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [failedUserMessages, setFailedUserMessages] = useState<PendingMessage[]>([]);
  const [hasLoadedHistory, setHasLoadedHistory] = useState(false);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isOlderHistoryLoading, setIsOlderHistoryLoading] = useState(false);
  const [pendingUserMessages, setPendingUserMessages] = useState<PendingMessage[]>([]);
  const [queuedMessages, setQueuedMessages] = useState<QueuedMessage[]>([]);
  const [selectedReferences, setSelectedReferences] = useState<AppReference[]>([]);
  const [targetConversationResolved, setTargetConversationResolved] = useState(false);
  const [threads, setThreads] = useState<ChatThread[]>(initialThreads);
  void activeInterAgentGraphRunId;
  void activeSession;
  void activeTurn;
  void composer;
  void events;
  void failedUserMessages;
  void isHistoryLoading;
  void isOlderHistoryLoading;
  void pendingUserMessages;
  void queuedMessages;
  void selectedReferences;

  const navigation = useChatNavigation({
    activeAppContext: null,
    activeSession,
    activeThread,
    activeTurn,
    clearAttachments: vi.fn(),
    events,
    hasExternalRuntimeThreads: false,
    hasLoadedHistory,
    hasMoreHistory,
    isBootstrapping,
    navigationScope: "test",
    newChatProjectId: null,
    newChatRequestId: null,
    notifyActiveThreadChanged: vi.fn(),
    runtimeThreads: null,
    runtimeThreadsError: null,
    runtimeThreadsLoaded: false,
    setActiveInterAgentGraphRunId,
    setActiveSession,
    setActiveThread,
    setActiveTurn,
    setComposer,
    setDraftChat,
    setError,
    setEvents,
    setFailedUserMessages,
    setFailedUserMessagesForConversation: vi.fn(),
    setHasLoadedHistory,
    setHasMoreHistory,
    setIsBootstrapping,
    setIsHistoryLoading,
    setIsOlderHistoryLoading,
    setPendingUserMessages,
    setPendingUserMessagesForConversation: vi.fn(),
    setQueuedMessages,
    setQueuedMessagesForConversation: vi.fn(),
    setSelectedReferences,
    setTargetConversationResolved,
    setThreads,
    threadId,
    threads,
  });

  useEffect(() => {
    onNavigationReady?.(navigation);
  }, [navigation, onNavigationReady]);

  useEffect(() => {
    onState({ activeThread, draftChat, error, isBootstrapping, targetConversationResolved, threads });
  }, [activeThread, draftChat, error, isBootstrapping, onState, targetConversationResolved, threads]);

  return null;
}

async function flushEffects() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function waitForAssertion(assertion: () => void) {
  let lastError: unknown;
  for (let index = 0; index < 8; index += 1) {
    await flushEffects();
    try {
      assertion();
      return;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

describe("useChatNavigation initial selection and deep links", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    window.history.replaceState(null, "", "/apps/chat/");
    catalogMocks.threadsLoaded = true;
    apiMocks.createThread.mockReset();
    apiMocks.getRuntimeThread.mockReset();
    apiMocks.isRuntimeSessionUnavailableError.mockClear();
    shellMocks.openChatRootRouteInShell.mockClear();
    shellMocks.openChatThreadRouteInShell.mockClear();
    transcriptMocks.handleUnavailableRuntimeSession.mockClear();
    transcriptMocks.setActiveRuntimeSessionId.mockClear();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it.each(["free", "busy", "quarantined"])("starts a new chat instead of selecting the first %s thread", async (availability) => {
    const states: ProbeState[] = [];
    await act(async () => {
      root.render(<NavigationProbe initialThreads={[thread({ availability })]} onState={(state) => states.push(state)} threadId={null} />);
    });

    await waitForAssertion(() => {
      expect(states.at(-1)?.draftChat?.draftId).toBe("active");
      expect(states.at(-1)?.isBootstrapping).toBe(false);
    });
    expect(states.at(-1)?.activeThread).toBeNull();
    expect(states.at(-1)?.targetConversationResolved).toBe(true);
    expect(states.at(-1)?.error).toBeNull();
    expect(apiMocks.getRuntimeThread).not.toHaveBeenCalled();
    expect(apiMocks.createThread).not.toHaveBeenCalled();
    expect(transcriptMocks.setActiveRuntimeSessionId).not.toHaveBeenCalled();
    expect(shellMocks.openChatRootRouteInShell).not.toHaveBeenCalled();
  });

  it("opens a thread explicitly requested in the URL", async () => {
    const states: ProbeState[] = [];
    window.history.replaceState(null, "", "/apps/chat/?thread_id=requested-thread");
    await act(async () => {
      root.render(<NavigationProbe initialThreads={[thread(), thread({ thread_id: "requested-thread" })]} onState={(state) => states.push(state)} threadId={null} />);
    });
    await waitForAssertion(() => expect(states.at(-1)?.activeThread?.thread_id).toBe("requested-thread"));
    expect(states.at(-1)?.draftChat).toBeNull();
  });

  it("opens delayed shell navigation without replacing its route with the initial draft", async () => {
    const states: ProbeState[] = [];
    let navigation: ReturnType<typeof useChatNavigation>;
    const selectedThread = thread({ thread_id: "selected-thread" });
    await act(async () => {
      root.render(<NavigationProbe initialThreads={[thread(), selectedThread]}
        onNavigationReady={(value) => { navigation = value; }} onState={(state) => states.push(state)} threadId={null} />);
    });
    expect(states.at(-1)?.draftChat?.draftId).toBe("active");
    expect(shellMocks.openChatRootRouteInShell).not.toHaveBeenCalled();

    await act(async () => navigation.handleNavigationParams({ app_page: "threads/selected-thread" }));

    expect(states.at(-1)?.activeThread?.thread_id).toBe("selected-thread");
    expect(states.at(-1)?.draftChat).toBeNull();
    expect(shellMocks.openChatRootRouteInShell).not.toHaveBeenCalled();
    expect(shellMocks.openChatThreadRouteInShell).toHaveBeenCalledWith("selected-thread", { navigationScope: "test" });
  });

  it("keeps pending shell navigation authoritative when the catalog arrives during its read", async () => {
    catalogMocks.threadsLoaded = false;
    const states: ProbeState[] = [];
    let navigation: ReturnType<typeof useChatNavigation>;
    let resolveThread!: (value: ChatThread) => void;
    apiMocks.getRuntimeThread.mockReturnValue(new Promise<ChatThread>((resolve) => { resolveThread = resolve; }));
    const renderProbe = () => root.render(<NavigationProbe initialThreads={[thread()]}
      onNavigationReady={(value) => { navigation = value; }} onState={(state) => states.push(state)} threadId={null} />);
    await act(async () => renderProbe());

    let pendingNavigation!: Promise<void>;
    await act(async () => {
      pendingNavigation = navigation.handleNavigationParams({ app_page: "threads/selected-thread" });
    });
    catalogMocks.threadsLoaded = true;
    await act(async () => renderProbe());

    expect(states.at(-1)?.isBootstrapping).toBe(true);
    expect(states.at(-1)?.draftChat).toBeNull();
    expect(states.at(-1)?.activeThread).toBeNull();
    expect(shellMocks.openChatRootRouteInShell).not.toHaveBeenCalled();
    await act(async () => {
      resolveThread(thread({ thread_id: "selected-thread" }));
      await pendingNavigation;
    });
    expect(states.at(-1)?.activeThread?.thread_id).toBe("selected-thread");
    expect(states.at(-1)?.draftChat).toBeNull();
    expect(states.at(-1)?.isBootstrapping).toBe(false);
  });

  it.each([403, 503])("keeps a %s thread read failure visible without substituting another chat", async (status) => {
    const states: ProbeState[] = [];
    apiMocks.getRuntimeThread.mockRejectedValue(new ApiError("Unable to open chat.", { path: "/api/runtime/threads/selected-thread", status }));
    await act(async () => {
      root.render(<NavigationProbe initialThreads={[thread()]} onState={(state) => states.push(state)} threadId="selected-thread" />);
    });
    await waitForAssertion(() => expect(states.at(-1)?.error).toBe("Unable to open chat."));
    expect(states.at(-1)?.activeThread).toBeNull();
    expect(states.at(-1)?.draftChat).toBeNull();
    expect(states.at(-1)?.targetConversationResolved).toBe(false);
    expect(shellMocks.openChatRootRouteInShell).not.toHaveBeenCalled();
  });

  it("opens an existing deep-linked thread that is outside the local catalog", async () => {
    const states: ProbeState[] = [];
    const fetchedThread = thread({ thread_id: "deep-thread", runtime_session_id: "deep-session", system_prompt: "detail prompt" });
    apiMocks.getRuntimeThread.mockResolvedValue(fetchedThread);

    await act(async () => {
      root.render(<NavigationProbe onState={(state) => states.push(state)} threadId="deep-thread" />);
    });

    await waitForAssertion(() => {
      expect(states.at(-1)?.activeThread?.thread_id).toBe("deep-thread");
    });

    expect(apiMocks.getRuntimeThread).toHaveBeenCalledWith("deep-thread");
    expect(states.at(-1)?.threads.map((item) => item.thread_id)).toContain("deep-thread");
    expect(states.at(-1)?.targetConversationResolved).toBe(true);
    expect(states.at(-1)?.error).toBeNull();
    expect(transcriptMocks.setActiveRuntimeSessionId).toHaveBeenCalledWith("deep-session");
  });

  it("falls back to a new chat when a deep-linked thread is confirmed missing", async () => {
    const states: ProbeState[] = [];
    apiMocks.getRuntimeThread.mockRejectedValue(
      new ApiError("runtime_thread_not_found", {
        path: "/api/runtime/threads/missing-thread",
        status: 404,
      }),
    );

    await act(async () => {
      root.render(<NavigationProbe onState={(state) => states.push(state)} threadId="missing-thread" />);
    });

    await waitForAssertion(() => {
      expect(states.at(-1)?.error).toBe("This chat is no longer available.");
    });

    expect(apiMocks.getRuntimeThread).toHaveBeenCalledWith("missing-thread");
    expect(states.at(-1)?.activeThread).toBeNull();
    expect(states.at(-1)?.targetConversationResolved).toBe(true);
    expect(states.at(-1)?.draftChat?.draftId).toBe("active");
    expect(shellMocks.openChatRootRouteInShell).toHaveBeenCalled();
  });
});
