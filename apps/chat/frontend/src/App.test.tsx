/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import {
  createRuntimeSession,
  createRuntimeSessionWithTurn,
  createThread,
  getAgentDefinition,
  getAppDependencies,
  getSpeechCapabilities,
  interruptRuntimeTurn,
  listAgentCatalog,
  listApps,
  listInterAgentRunApprovals,
  listInterAgentRunArtifacts,
  listInterAgentRunEvents,
  listInterAgentRuns,
  listProviders,
  listSkills,
  prepareRuntimeSessionAppReferences,
  prewarmRuntimeSession,
  prewarmSpeechWorker,
  previewAgentPrompt,
  recordRuntimeTurnClientMetrics,
  sendRuntimeTurn,
  uploadWorkspaceFile,
} from "./api/client";
import type { AgentTypeSummary, AppDependenciesPayload, ChatThread, RuntimeSession, RuntimeTurn } from "./api/client";
import { clearAgentRuntimeConfigCache } from "./hooks/useChatRuntimeControls";

vi.mock("./hooks/useRuntimeEvents", () => ({
  useRuntimeEvents: vi.fn(),
}));

vi.mock("./hooks/useRuntimeThreads", async () => {
  const React = await import("react");
  return {
    useRuntimeThreads: ({ onSnapshot, setThreads }: { onSnapshot: () => void; setThreads: (threads: unknown[]) => void }) => {
      React.useEffect(() => {
        setThreads([]);
        onSnapshot();
      }, []);
    },
  };
});

const MockApiError = vi.hoisted(
  () =>
    class MockApiError extends Error {
      path: string;
      status: number;

      constructor(message: string, { path, status }: { path: string; status: number }) {
        super(message);
        this.name = "ApiError";
        this.path = path;
        this.status = status;
      }
    },
);

vi.mock("./api/client", () => ({
  ApiError: MockApiError,
  applyThreadCatalogPayload: vi.fn((current: ChatThread[], payload: { changed_thread?: ChatThread; thread?: ChatThread; threads?: ChatThread[] }) => {
    if (Array.isArray(payload.threads)) {
      return payload.threads;
    }
    const changedThread = payload.changed_thread || payload.thread;
    if (!changedThread) {
      return current;
    }
    return [...current.filter((thread) => thread.thread_id !== changedThread.thread_id), changedThread];
  }),
  createRuntimeSession: vi.fn(),
  createRuntimeSessionWithTurn: vi.fn(),
  createThread: vi.fn(),
  getAgentDefinition: vi.fn(),
  getAppDependencies: vi.fn(),
  getRuntimeThread: vi.fn(async (threadId: string) => {
    throw new MockApiError("runtime_thread_not_found", {
      path: `/api/runtime/threads/${encodeURIComponent(threadId)}`,
      status: 404,
    });
  }),
  getSpeechCapabilities: vi.fn(),
  getWidgetContext: vi.fn(),
  getInterAgentRun: vi.fn(),
  interAgentWebSocketUrl: vi.fn(() => "ws://maverick.test/ws/inter-agent/runs/run-1"),
  interruptInterAgentRun: vi.fn(),
  interruptRuntimeTurn: vi.fn(),
  isRuntimeSessionUnavailableError: vi.fn(() => false),
  listAgentCatalog: vi.fn(),
  listApps: vi.fn(),
  listInterAgentRunApprovals: vi.fn(),
  listInterAgentRunArtifacts: vi.fn(),
  listInterAgentRunEvents: vi.fn(),
  listInterAgentRuns: vi.fn(),
  listProviders: vi.fn(),
  listSkills: vi.fn(),
  markThreadRead: vi.fn(),
  orderChatThreads: vi.fn((threads: unknown[]) => threads),
  prepareRuntimeSessionAppReferences: vi.fn(),
  prewarmRuntimeSession: vi.fn(),
  prewarmSpeechWorker: vi.fn(),
  previewAgentPrompt: vi.fn(),
  recordRuntimeTurnClientMetrics: vi.fn(),
  closeInterAgentRun: vi.fn(),
  selectProvider: vi.fn(),
  resolveInterAgentApproval: vi.fn(),
  resumeInterAgentRun: vi.fn(),
  selectedDependencyProviderAppId: (payload: AppDependenciesPayload, alias: string) =>
    payload.dependencies.find((dependency) => dependency.alias === alias)?.selected_provider_app_ids[0] || "",
  selectedSharedDependencyProviderAppId: (payload: AppDependenciesPayload, aliases: string[]) => {
    const providerIds = aliases.map((alias) => payload.dependencies.find((dependency) => dependency.alias === alias)?.selected_provider_app_ids[0] || "");
    return providerIds.length && providerIds.every((providerId) => providerId && providerId === providerIds[0]) ? providerIds[0] : "";
  },
  sendRuntimeTurn: vi.fn(),
  uploadWorkspaceFile: vi.fn(),
}));

const socialVideoAgent: AgentTypeSummary = {
  id: "agent-type-social-video-content-strategist",
  name: "Social Video Content Strategist",
  description: "Turns notes into high-retention social video scripts.",
  role_id: "social-video-content-strategist",
  skill_ids: [],
  trace_verbosity: "compact",
  enabled: true,
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function dependencyPayload(selectedProviderAppIds: string[]): AppDependenciesPayload {
  const status = selectedProviderAppIds.length ? "resolved" : "optional_unset";
  return {
    workspace_id: "default",
    consumer_app_id: "chat",
    status,
    dependencies: [
      {
        alias: "agent-catalog",
        interface: "agent.catalog",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Agent catalog",
        status,
        candidates: [],
        selected_provider_app_ids: selectedProviderAppIds,
        stale_provider_app_ids: [],
        blocked_reason: null,
      },
      {
        alias: "agent-prompt-materializer",
        interface: "agent.prompt-materializer",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Agent prompt materializer",
        status,
        candidates: [],
        selected_provider_app_ids: selectedProviderAppIds,
        stale_provider_app_ids: [],
        blocked_reason: null,
      },
      {
        alias: "text-to-speech",
        interface: "speech.synthesis",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Speech synthesis",
        status: "resolved",
        candidates: [],
        selected_provider_app_ids: ["speech"],
        stale_provider_app_ids: [],
        blocked_reason: null,
      },
      {
        alias: "speech-to-text",
        interface: "speech.transcription",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Speech transcription",
        status: "resolved",
        candidates: [],
        selected_provider_app_ids: ["speech"],
        stale_provider_app_ids: [],
        blocked_reason: null,
      },
    ],
  };
}

function thread(threadId: string, runtimeSessionId: string, overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    thread_id: threadId,
    runtime_session_id: runtimeSessionId,
    title: "New chat",
    agent_label: "",
    agent_type_id: "",
    agent_role_id: "",
    source_app_id: "chat",
    system_prompt: "",
    project_id: null,
    archived: false,
    availability: "free",
    created_at: "2026-05-21T00:00:00Z",
    updated_at: "2026-05-21T00:00:00Z",
    last_user_message_at: null,
    ...overrides,
  };
}

function runtimeSession(sessionId: string): RuntimeSession {
  return {
    session_id: sessionId,
    workspace_id: "default",
    agent_id: "chat",
    status: "running",
    effective_mode: "sandbox",
  };
}

function hotRuntimeSession(sessionId: string): RuntimeSession {
  return {
    ...runtimeSession(sessionId),
    prewarm_status: "completed",
    prewarm_completed: true,
    provider_thread_ready: true,
  };
}

function runtimeTurn(turnId: string, sessionId: string, status = "queued"): RuntimeTurn {
  return {
    turn_id: turnId,
    session_id: sessionId,
    workspace_id: "default",
    status,
    input_text: "hello",
    failure_reason: null,
    created_at: "2026-05-21T00:00:01Z",
    updated_at: "2026-05-21T00:00:01Z",
  };
}

function uploadedWorkspaceFile(filename: string) {
  return {
    file: {
      file_id: `file-${filename}`,
      workspace_id: "default",
      relative_path: `storage/uploads/${filename}`,
      filename,
      content_type: "text/plain",
      size_bytes: 12,
      sha256: "sha256",
      created_at: "2026-05-21T00:00:00Z",
    },
  };
}

beforeEach(() => {
  window.localStorage.clear();
  clearAgentRuntimeConfigCache();
  vi.mocked(listProviders).mockResolvedValue({
    workspace_id: "default",
    active_provider: {
      provider_id: "codex",
      label: "Codex",
      description: "Local agentic runtime",
      kind: "runtime_backend",
      provider_role: "runtime_engine",
      status: "active",
      default_model_family: "gpt-5.6-sol",
    },
    items: [],
  });
  vi.mocked(listApps).mockResolvedValue([]);
  vi.mocked(listInterAgentRuns).mockResolvedValue({ items: [] });
  vi.mocked(listInterAgentRunEvents).mockResolvedValue({
    items: [],
    visibility_plane: "summary",
    limit: 80,
    has_more_before: false,
    has_more_after: false,
    oldest_event_id: null,
    newest_event_id: null,
  });
  vi.mocked(listInterAgentRunApprovals).mockResolvedValue({ items: [] });
  vi.mocked(listInterAgentRunArtifacts).mockResolvedValue({
    items: [],
    visibility_plane: "detail",
    limit: 80,
    has_more_before: false,
    has_more_after: false,
    oldest_event_id: null,
    newest_event_id: null,
  });
  vi.mocked(listSkills).mockResolvedValue([]);
  vi.mocked(getAppDependencies).mockResolvedValue(dependencyPayload(["agents"]));
  vi.mocked(getSpeechCapabilities).mockResolvedValue({
    interfaces: {
      "speech.synthesis": {
        available: true,
        provider_available: true,
      },
      "speech.transcription": {
        available: true,
        provider_available: true,
      },
    },
  });
  vi.mocked(listAgentCatalog).mockResolvedValue({ agent_types: [socialVideoAgent] });
  vi.mocked(getAgentDefinition).mockResolvedValue({ exists: true, agent_definition: socialVideoAgent });
  vi.mocked(previewAgentPrompt).mockResolvedValue({ rendered: "Agent prompt" });
  vi.mocked(prepareRuntimeSessionAppReferences).mockResolvedValue({
    session_id: "session-prepared",
    status: "ready",
    reference_count: 0,
    materialized_reference_count: 0,
    reference_cache_hit: false,
    reference_fingerprint: "",
  });
  vi.mocked(prewarmRuntimeSession).mockResolvedValue(hotRuntimeSession("session-prewarmed"));
  vi.mocked(prewarmSpeechWorker).mockResolvedValue({});
  vi.mocked(createRuntimeSession).mockRejectedValue(new Error("prepared session unavailable in default fixture"));
  vi.mocked(createRuntimeSessionWithTurn).mockResolvedValue({
    session: runtimeSession("session-prepared"),
    thread: thread("session-prepared", "session-prepared"),
    turn: runtimeTurn("turn-prepared", "session-prepared"),
    events: [],
  });
  vi.mocked(recordRuntimeTurnClientMetrics).mockResolvedValue({
    status: "recorded",
    turn_id: "turn-prepared",
    metric_count: 1,
  });
  vi.mocked(sendRuntimeTurn).mockResolvedValue({
    session: runtimeSession("session-prepared"),
    thread: thread("session-prepared", "session-prepared"),
    turn: runtimeTurn("turn-prepared", "session-prepared"),
    events: [],
  });
  vi.mocked(uploadWorkspaceFile).mockResolvedValue(uploadedWorkspaceFile("default.txt"));
  vi.mocked(interruptRuntimeTurn).mockResolvedValue({
    turn: runtimeTurn("turn-stopped", "session-created", "cancelled"),
    interrupted: true,
  });
});

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  vi.clearAllMocks();
  clearAgentRuntimeConfigCache();
  window.localStorage.clear();
});

async function renderApp(props: Parameters<typeof App>[0] = {}) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root?.render(<App {...props} />);
  });
  return container;
}

async function waitForAssertion(assertion: () => void) {
  let lastError: unknown;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      assertion();
      return;
    } catch (error) {
      lastError = error;
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    }
  }
  throw lastError;
}

async function typeComposerMessage(element: HTMLElement, message: string) {
  const editor = element.querySelector('[role="textbox"]') as HTMLElement | null;
  if (!editor) {
    throw new Error("Composer textbox was not rendered.");
  }
  await act(async () => {
    editor.textContent = message;
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function clickSend(element: HTMLElement) {
  const sendButton = element.querySelector('[aria-label="Send message"], [aria-label="Queue message"]') as HTMLButtonElement | null;
  if (!sendButton) {
    throw new Error("Send button was not rendered.");
  }
  await act(async () => {
    sendButton.click();
  });
}

async function addAttachment(element: HTMLElement, filename: string, contentType: string) {
  const fileInput = element.querySelector('input[type="file"]') as HTMLInputElement | null;
  if (!fileInput) {
    throw new Error("Attachment file input was not rendered.");
  }
  const file = new File(["attachment"], filename, { type: contentType });
  Object.defineProperty(fileInput, "files", {
    configurable: true,
    value: [file],
  });
  await act(async () => {
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function addTextAttachment(element: HTMLElement, filename = "notes.txt") {
  await addAttachment(element, filename, "text/plain");
}

async function addImageAttachment(element: HTMLElement, filename = "photo.png") {
  await addAttachment(element, filename, "image/png");
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

describe("App agent catalog dependency refresh", () => {
  it("preloads selected agent runtime configuration before the first send", async () => {
    const element = await renderApp();

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });

    await act(async () => {
      (element.querySelector('[aria-label="Agent runner: Default Chat"]') as HTMLButtonElement | null)?.click();
    });
    await act(async () => {
      (Array.from(element.querySelectorAll('[role="option"]')).find((option) =>
        option.textContent?.includes("Social Video Content Strategist"),
      ) as HTMLButtonElement | undefined)?.click();
    });

    await waitForAssertion(() => {
      expect(getAgentDefinition).toHaveBeenCalledWith("agents", socialVideoAgent.id);
      expect(previewAgentPrompt).toHaveBeenCalledWith("agents", socialVideoAgent.id);
    });
  });

  it("does not block the initial composer on speech capability loading", async () => {
    const capabilities = deferred<Awaited<ReturnType<typeof getSpeechCapabilities>>>();
    vi.mocked(getSpeechCapabilities).mockReturnValue(capabilities.promise);

    const element = await renderApp();

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });
    expect(getSpeechCapabilities).toHaveBeenCalled();

    capabilities.resolve({ interfaces: {} });
    await act(async () => {
      await capabilities.promise;
    });
  });

  it("prewarms the selected speech transcription provider when capabilities are available", async () => {
    await renderApp();

    await waitForAssertion(() => {
      expect(prewarmSpeechWorker).toHaveBeenCalledWith("speech");
    });
  });

  it("does not prewarm transcription when the inline default profile is unavailable", async () => {
    vi.mocked(getSpeechCapabilities).mockResolvedValue({
      interfaces: {
        "speech.synthesis": {
          available: true,
          provider_available: true,
        },
        "speech.transcription": {
          available: true,
          provider_available: true,
          inline_default_profile_available: false,
        },
      },
    });

    await renderApp();

    await waitForAssertion(() => {
      expect(getSpeechCapabilities).toHaveBeenCalledWith("speech");
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(prewarmSpeechWorker).not.toHaveBeenCalled();
  });

  it("clears stale agent options when a dependency refresh cannot load the selected catalog", async () => {
    const element = await renderApp();

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });

    const agentButton = () => element.querySelector('[aria-label="Agent runner: Default Chat"]') as HTMLButtonElement | null;
    await act(async () => {
      agentButton()?.click();
    });
    await waitForAssertion(() => {
      expect(element.textContent).toContain("Social Video Content Strategist");
    });

    vi.mocked(listAgentCatalog).mockRejectedValueOnce(new Error("catalog unavailable"));

    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          data: {
            type: "maverick.app.dependencies",
            app_id: "chat",
            dependencies: dependencyPayload(["agents"]),
          },
        }),
      );
    });

    await waitForAssertion(() => {
      expect(element.textContent).not.toContain("Social Video Content Strategist");
      expect(element.textContent).toContain("No agent catalog available");
    });
  });
});

describe("App thread navigation", () => {
  it("does not allow sending to a draft when a requested thread is missing", async () => {
    const element = await renderApp({ runtimeThreads: [] as ChatThread[], runtimeThreadsLoaded: true, threadId: "missing-thread" });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("This chat is no longer available.");
      expect(element.querySelector('[role="textbox"]')?.getAttribute("aria-disabled")).toBe("true");
      expect((element.querySelector('[aria-label="Send message"]') as HTMLButtonElement | null)?.disabled).toBe(true);
    });
  });

  it("prewarms the active runtime thread and keeps a next-chat session ready", async () => {
    const existingThread = thread("thread-existing", "session-existing", { title: "Existing thread" });
    await renderApp({
      runtimeThreads: [existingThread],
      runtimeThreadsLoaded: true,
      threadId: existingThread.thread_id,
    });

    await waitForAssertion(() => {
      expect(prewarmRuntimeSession).toHaveBeenCalledWith(
        "session-existing",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });
    expect(createRuntimeSession).toHaveBeenCalledWith(
      expect.objectContaining({
        prepare_only: true,
        title: "New chat",
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("starts a new-chat draft before runtime threads and agent catalog finish loading", async () => {
    const catalog = deferred<Awaited<ReturnType<typeof listAgentCatalog>>>();
    vi.mocked(listAgentCatalog).mockReturnValue(catalog.promise);

    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-fast-draft",
      runtimeThreads: [] as ChatThread[],
      runtimeThreadsLoaded: false,
    });

    await waitForAssertion(() => {
      expect(listAgentCatalog).toHaveBeenCalled();
      expect(element.textContent).toContain("How can I help today?");
      expect(element.querySelector('[role="textbox"]')?.getAttribute("aria-disabled")).toBe("false");
      expect(element.querySelector('[aria-label="Agent runner: Loading agents..."]')).toBeTruthy();
    });

    catalog.resolve({ agent_types: [socialVideoAgent] });
    await act(async () => {
      await catalog.promise;
    });
  });

  it("shows external runtime thread stream errors when the catalog is owned by a parent widget", async () => {
    const element = await renderApp({
      runtimeThreads: [] as ChatThread[],
      runtimeThreadsError: "Runtime thread stream is not authorized.",
      runtimeThreadsLoaded: false,
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("Runtime thread stream is not authorized.");
    });
  });

  it("starts a draft from a new-chat request id before selecting an existing thread", async () => {
    const existingThread = thread("thread-existing", "session-existing", { title: "Existing thread" });
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatProjectId: "project-1",
      newChatRequestId: "request-1",
      runtimeThreads: [existingThread],
      runtimeThreadsLoaded: true,
      threadId: existingThread.thread_id,
    });

    await waitForAssertion(() => {
      expect(listApps).toHaveBeenCalled();
      expect(element.textContent).toContain("How can I help today?");
    });
  });

  it("starts a draft when a mounted floating app receives a later new-chat request id", async () => {
    const existingThread = thread("thread-existing", "session-existing", { title: "Existing thread" });
    const element = await renderApp({
      navigationScope: "floating-window",
      runtimeThreads: [existingThread],
      runtimeThreadsLoaded: true,
      threadId: existingThread.thread_id,
    });

    await waitForAssertion(() => {
      expect(listApps).toHaveBeenCalled();
      expect(element.textContent).not.toContain("How can I help today?");
    });

    await act(async () => {
      root?.render(
        <App
          navigationScope="floating-window"
          newChatProjectId="project-1"
          newChatRequestId="request-2"
          runtimeThreads={[existingThread]}
          runtimeThreadsLoaded
          threadId={existingThread.thread_id}
        />,
      );
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });
  });

  it("opens a selected thread when a mounted floating app receives a new thread id", async () => {
    const firstThread = thread("thread-first", "session-first", { title: "First thread" });
    const secondThread = thread("thread-second", "session-second", { title: "Second thread" });
    const element = await renderApp({
      navigationScope: "floating-window",
      runtimeThreads: [firstThread, secondThread],
      runtimeThreadsLoaded: true,
      threadId: firstThread.thread_id,
    });

    await waitForAssertion(() => {
      expect(listApps).toHaveBeenCalled();
      expect(element.textContent).not.toContain("How can I help today?");
    });

    const postMessageSpy = vi.spyOn(window.parent, "postMessage");

    await act(async () => {
      root?.render(
        <App
          navigationScope="floating-window"
          runtimeThreads={[firstThread, secondThread]}
          runtimeThreadsLoaded
          threadId={secondThread.thread_id}
        />,
      );
    });

    await waitForAssertion(() => {
      expect(postMessageSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          active_thread_id: secondThread.thread_id,
          navigation_scope: "floating-window",
          owner_app_id: "chat",
          type: "maverick.chat.active-thread-changed",
        }),
        window.location.origin,
      );
    });
  });

  it("does not let a slow draft submit steal the active thread after navigation", async () => {
    const existingThread = thread("thread-existing", "session-existing", { title: "Existing thread" });
    const createdThread = thread("thread-created", "session-created", { title: "Created thread" });
    const submitTurn = deferred<Awaited<ReturnType<typeof createRuntimeSessionWithTurn>>>();
    vi.mocked(createRuntimeSessionWithTurn).mockReturnValue(submitTurn.promise);
    const postMessageSpy = vi.spyOn(window.parent, "postMessage");
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-slow",
      runtimeThreads: [existingThread],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });
    await typeComposerMessage(element, "hello");
    await clickSend(element);

    await waitForAssertion(() => {
      expect(createRuntimeSessionWithTurn).toHaveBeenCalledWith(
        expect.objectContaining({
          inputText: "hello",
        }),
      );
      expect(element.textContent).toContain("hello");
      expect(element.textContent).toContain("Starting");
    });

    await act(async () => {
      root?.render(
        <App
          navigationScope="floating-window"
          runtimeThreads={[existingThread]}
          runtimeThreadsLoaded
          threadId={existingThread.thread_id}
        />,
      );
    });
    await waitForAssertion(() => {
      expect(postMessageSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          active_thread_id: existingThread.thread_id,
          navigation_scope: "floating-window",
          owner_app_id: "chat",
          type: "maverick.chat.active-thread-changed",
        }),
        window.location.origin,
      );
    });

    await act(async () => {
      submitTurn.resolve({
        session: runtimeSession("session-created"),
        thread: createdThread,
        turn: runtimeTurn("turn-created", "session-created"),
        events: [],
      });
      await submitTurn.promise;
    });

    expect(postMessageSpy).not.toHaveBeenCalledWith(
      expect.objectContaining({
        active_thread_id: createdThread.thread_id,
        navigation_scope: "floating-window",
        owner_app_id: "chat",
        type: "maverick.chat.active-thread-changed",
      }),
      window.location.origin,
    );
  });

  it("submits first-turn app references without waiting for pending reference preparation", async () => {
    const createdThread = thread("thread-created", "session-created", { title: "Created thread" });
    vi.mocked(createRuntimeSessionWithTurn).mockResolvedValue({
      session: runtimeSession("session-created"),
      thread: createdThread,
      turn: runtimeTurn("turn-created", "session-created"),
      events: [],
    });
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-reference-submit",
      runtimeThreads: [],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });
    await typeComposerMessage(element, "review @Notes [ref:storage/file/file_1]");
    await clickSend(element);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 225));
    });

    await waitForAssertion(() => {
      expect(createRuntimeSessionWithTurn).toHaveBeenCalledWith(
        expect.objectContaining({
          inputText: "review @Notes [ref:storage/file/file_1]",
          appReferences: [
            expect.objectContaining({
              app_id: "storage",
              entity_id: "file_1",
              entity_type: "file",
              type: "entity",
            }),
          ],
        }),
      );
    });
    expect(prepareRuntimeSessionAppReferences).not.toHaveBeenCalled();
    expect(sendRuntimeTurn).not.toHaveBeenCalled();
  });

  it("prepares app references while typing in an existing thread", async () => {
    const existingThread = thread("thread-existing", "session-existing", { title: "Existing thread" });
    const element = await renderApp({
      runtimeThreads: [existingThread],
      runtimeThreadsLoaded: true,
      threadId: existingThread.thread_id,
    });

    await waitForAssertion(() => {
      expect(element.querySelector('[role="textbox"]')).not.toBeNull();
    });
    await typeComposerMessage(element, "review @Notes [ref:storage/file/file_1]");

    await waitForAssertion(() => {
      expect(prepareRuntimeSessionAppReferences).toHaveBeenCalledWith(
        "session-existing",
        [
          expect.objectContaining({
            app_id: "storage",
            entity_id: "file_1",
            entity_type: "file",
          }),
        ],
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });
  });

  it("uploads an image immediately after selection and reuses it on submit", async () => {
    const upload = deferred<Awaited<ReturnType<typeof uploadWorkspaceFile>>>();
    vi.mocked(uploadWorkspaceFile).mockReturnValue(upload.promise);
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-image-preupload",
      runtimeThreads: [],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });
    await addImageAttachment(element);

    await waitForAssertion(() => {
      expect(uploadWorkspaceFile).toHaveBeenCalledTimes(1);
    });
    expect(createRuntimeSessionWithTurn).not.toHaveBeenCalled();

    await act(async () => {
      upload.resolve(uploadedWorkspaceFile("photo.png"));
      await upload.promise;
      await Promise.resolve();
    });
    await typeComposerMessage(element, "review this photo");
    await clickSend(element);

    await waitForAssertion(() => {
      expect(createRuntimeSessionWithTurn).toHaveBeenCalledWith(
        expect.objectContaining({
          attachments: [
            expect.objectContaining({
              fileId: "file-photo.png",
              relativePath: "storage/uploads/photo.png",
            }),
          ],
          clientMetrics: expect.objectContaining({
            attachment_upload_ready_before_submit: true,
            attachment_upload_wait_on_submit_ms: expect.any(Number),
            attachment_upload_ms: expect.any(Number),
          }),
        }),
      );
    });
    expect(uploadWorkspaceFile).toHaveBeenCalledTimes(1);
  });

  it("keeps uploaded draft attachments bound to the original draft after navigation", async () => {
    const existingThread = thread("thread-existing", "session-existing", { title: "Existing thread" });
    const createdThread = thread("thread-created", "session-created", { title: "Created thread" });
    const upload = deferred<Awaited<ReturnType<typeof uploadWorkspaceFile>>>();
    const submitTurn = deferred<Awaited<ReturnType<typeof createRuntimeSessionWithTurn>>>();
    vi.mocked(uploadWorkspaceFile).mockReturnValue(upload.promise);
    vi.mocked(createRuntimeSessionWithTurn).mockReturnValue(submitTurn.promise);
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-upload",
      runtimeThreads: [existingThread],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });
    await addTextAttachment(element);
    await typeComposerMessage(element, "hello with attachment");
    await clickSend(element);

    await waitForAssertion(() => {
      expect(uploadWorkspaceFile).toHaveBeenCalled();
      expect(element.textContent).toContain("hello with attachment");
      expect(element.textContent).toContain("Starting");
      expect(element.querySelector('[aria-label="Stop chat"]')).not.toBeNull();
    });

    await act(async () => {
      root?.render(
        <App
          navigationScope="floating-window"
          runtimeThreads={[existingThread]}
          runtimeThreadsLoaded
          threadId={existingThread.thread_id}
        />,
      );
    });

    await act(async () => {
      upload.resolve(uploadedWorkspaceFile("notes.txt"));
      await upload.promise;
    });

    await waitForAssertion(() => {
      expect(createRuntimeSessionWithTurn).toHaveBeenCalledWith(
        expect.objectContaining({
          inputText: "hello with attachment",
          attachments: expect.arrayContaining([
            expect.objectContaining({
              fileId: "file-notes.txt",
              relativePath: "storage/uploads/notes.txt",
            }),
          ]),
        }),
      );
    });
    expect(sendRuntimeTurn).not.toHaveBeenCalledWith(
      existingThread.runtime_session_id,
      expect.any(String),
      expect.any(String),
      expect.any(Array),
      expect.any(Array),
      expect.any(Object),
    );

    await act(async () => {
      submitTurn.resolve({
        session: runtimeSession("session-created"),
        thread: createdThread,
        turn: runtimeTurn("turn-created", "session-created"),
        events: [],
      });
      await submitTurn.promise;
    });
  });

  it("sends a queued attachment after its upload resolves behind draft migration", async () => {
    const createdThread = thread("thread-created", "session-created", { title: "Created thread" });
    const upload = deferred<Awaited<ReturnType<typeof uploadWorkspaceFile>>>();
    const firstTurn = deferred<Awaited<ReturnType<typeof createRuntimeSessionWithTurn>>>();
    vi.mocked(uploadWorkspaceFile).mockReturnValue(upload.promise);
    vi.mocked(createRuntimeSessionWithTurn).mockReturnValueOnce(firstTurn.promise);
    vi.mocked(sendRuntimeTurn)
      .mockResolvedValueOnce({
        session: runtimeSession("session-created"),
        thread: createdThread,
        turn: runtimeTurn("turn-second", "session-created", "completed"),
        events: [],
      });
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-queued-upload",
      runtimeThreads: [],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });
    await typeComposerMessage(element, "first message");
    await clickSend(element);
    await waitForAssertion(() => {
      expect(createRuntimeSessionWithTurn).toHaveBeenCalledWith(
        expect.objectContaining({
          inputText: "first message",
        }),
      );
      expect(element.textContent).toContain("Starting");
    });

    await addTextAttachment(element);
    await typeComposerMessage(element, "second with attachment");
    await clickSend(element);
    await waitForAssertion(() => {
      expect(uploadWorkspaceFile).toHaveBeenCalled();
    });

    await act(async () => {
      firstTurn.resolve({
        session: runtimeSession("session-created"),
        thread: createdThread,
        turn: runtimeTurn("turn-created", "session-created", "completed"),
        events: [],
      });
      await firstTurn.promise;
    });
    expect(sendRuntimeTurn).not.toHaveBeenCalled();

    await act(async () => {
      upload.resolve(uploadedWorkspaceFile("notes.txt"));
      await upload.promise;
    });

    await waitForAssertion(() => {
      expect(sendRuntimeTurn).toHaveBeenCalledWith(
        "session-created",
        "second with attachment",
        expect.any(String),
        expect.arrayContaining([
          expect.objectContaining({
            fileId: "file-notes.txt",
            relativePath: "storage/uploads/notes.txt",
          }),
        ]),
        expect.any(Array),
        expect.any(Object),
      );
    });
  });

  it("aborts a draft submit before the runtime ack arrives", async () => {
    let submitSignal: AbortSignal | undefined;
    vi.mocked(createRuntimeSessionWithTurn).mockImplementation(
      ({ signal }) =>
        new Promise((resolve, reject) => {
          submitSignal = signal;
          signal?.addEventListener("abort", () => {
            reject(new DOMException("Stopped", "AbortError"));
          });
          void resolve;
        }),
    );
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-abort",
      runtimeThreads: [],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });
    await typeComposerMessage(element, "stop before ack");
    await clickSend(element);
    await waitForAssertion(() => {
      expect(element.textContent).toContain("Starting");
      expect(element.querySelector('[aria-label="Stop chat"]')).not.toBeNull();
    });

    await act(async () => {
      (element.querySelector('[aria-label="Stop chat"]') as HTMLButtonElement | null)?.click();
    });

    await waitForAssertion(() => {
      expect(submitSignal?.aborted).toBe(true);
      expect(element.textContent).not.toContain("Starting");
    });
  });

  it("aborts an attachment upload before runtime submission starts", async () => {
    const upload = deferred<Awaited<ReturnType<typeof uploadWorkspaceFile>>>();
    vi.mocked(uploadWorkspaceFile).mockReturnValue(upload.promise);
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-upload-abort",
      runtimeThreads: [],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });
    await addTextAttachment(element);
    await typeComposerMessage(element, "stop upload");
    await clickSend(element);

    await waitForAssertion(() => {
      expect(uploadWorkspaceFile).toHaveBeenCalled();
      expect(element.textContent).toContain("Starting");
      expect(element.querySelector('[aria-label="Stop chat"]')).not.toBeNull();
    });

    await act(async () => {
      (element.querySelector('[aria-label="Stop chat"]') as HTMLButtonElement | null)?.click();
    });

    await waitForAssertion(() => {
      expect(element.textContent).not.toContain("Starting");
    });
    await act(async () => {
      upload.resolve(uploadedWorkspaceFile("notes.txt"));
      await upload.promise;
    });
    expect(createRuntimeSessionWithTurn).not.toHaveBeenCalled();
    expect(sendRuntimeTurn).not.toHaveBeenCalled();
  });

  it("falls back to creating a session with the first turn when preparation fails", async () => {
    const createdThread = thread("thread-created", "session-created", { title: "Created thread" });
    vi.mocked(createRuntimeSession).mockRejectedValue(new Error("prepare failed"));
    vi.mocked(createRuntimeSessionWithTurn).mockResolvedValue({
      session: runtimeSession("session-created"),
      thread: createdThread,
      turn: runtimeTurn("turn-created", "session-created"),
      events: [],
    });
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-fallback",
      runtimeThreads: [],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });
    await typeComposerMessage(element, "fallback first message");
    await clickSend(element);

    await waitForAssertion(() => {
      expect(createRuntimeSessionWithTurn).toHaveBeenCalledWith(
        expect.objectContaining({
          inputText: "fallback first message",
        }),
      );
    });
    expect(sendRuntimeTurn).not.toHaveBeenCalled();
  });

  it("waits for the single-flight prepared session before a plain first submit", async () => {
    const preparedSession = deferred<RuntimeSession>();
    vi.mocked(createRuntimeSession).mockReturnValue(preparedSession.promise);
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-pending-prepared",
      runtimeThreads: [],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
      expect(createRuntimeSession).toHaveBeenCalled();
    });
    await typeComposerMessage(element, "fast first message");
    await clickSend(element);

    expect(createRuntimeSessionWithTurn).not.toHaveBeenCalled();
    await act(async () => {
      preparedSession.resolve(hotRuntimeSession("session-background-hot"));
      await preparedSession.promise;
    });
    await waitForAssertion(() => {
      expect(sendRuntimeTurn).toHaveBeenCalledWith(
        "session-background-hot",
        "fast first message",
        expect.any(String),
        [],
        [],
        expect.objectContaining({
          clientMetrics: expect.objectContaining({
            prepare_refs_wait_on_submit_ms: 0,
            prepared_session_ready_before_submit: false,
            prepared_session_wait_on_submit_ms: expect.any(Number),
          }),
        }),
      );
    });
    const prepareSignal = vi.mocked(createRuntimeSession).mock.calls[0]?.[1]?.signal;
    expect(prepareSignal?.aborted).toBe(false);
    const submittedMetrics = vi.mocked(sendRuntimeTurn).mock.calls[0]?.[5]?.clientMetrics;
    expect(submittedMetrics).not.toHaveProperty("attachment_upload_ms");
    expect(createRuntimeSessionWithTurn).not.toHaveBeenCalled();
    expect(prepareSignal?.aborted).toBe(false);
  });

  it("uses a prepared session only after provider prewarm is hot", async () => {
    vi.mocked(createRuntimeSession).mockResolvedValue(hotRuntimeSession("session-hot"));
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-hot-prepared",
      runtimeThreads: [],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(createRuntimeSession).toHaveBeenCalled();
    });
    await typeComposerMessage(element, "use hot session");
    await clickSend(element);

    await waitForAssertion(() => {
      expect(sendRuntimeTurn).toHaveBeenCalledWith(
        "session-hot",
        "use hot session",
        expect.any(String),
        [],
        [],
        expect.any(Object),
      );
    });
    expect(createRuntimeSessionWithTurn).not.toHaveBeenCalled();
  });

  it("starts and reuses runtime preload before a draft chat exists", async () => {
    vi.mocked(createRuntimeSession).mockResolvedValue(hotRuntimeSession("session-early-hot"));
    const element = await renderApp({
      navigationScope: "floating-window",
      runtimeThreads: [],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(createRuntimeSession).toHaveBeenCalledTimes(1);
    });
    await typeComposerMessage(element, "reuse early preload");
    await clickSend(element);

    await waitForAssertion(() => {
      expect(sendRuntimeTurn).toHaveBeenCalledWith(
        "session-early-hot",
        "reuse early preload",
        expect.any(String),
        [],
        [],
        expect.any(Object),
      );
    });
    await waitForAssertion(() => {
      expect(createRuntimeSession).toHaveBeenCalledTimes(2);
    });
    expect(createRuntimeSession).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        prepare_only: true,
        title: "New chat",
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(createRuntimeSessionWithTurn).not.toHaveBeenCalled();
  });

  it("interrupts the submitted turn id after the runtime ack arrives", async () => {
    const createdThread = thread("thread-created", "session-created", { title: "Created thread" });
    vi.mocked(createRuntimeSessionWithTurn).mockResolvedValue({
      session: runtimeSession("session-created"),
      thread: createdThread,
      turn: runtimeTurn("turn-created", "session-created"),
      events: [],
    });
    const element = await renderApp({
      navigationScope: "floating-window",
      newChatRequestId: "request-stop-turn",
      runtimeThreads: [],
      runtimeThreadsLoaded: true,
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });
    await typeComposerMessage(element, "stop after ack");
    await clickSend(element);
    await waitForAssertion(() => {
      expect(element.querySelector('[aria-label="Stop chat"]')).not.toBeNull();
    });

    await act(async () => {
      (element.querySelector('[aria-label="Stop chat"]') as HTMLButtonElement | null)?.click();
    });

    await waitForAssertion(() => {
      expect(interruptRuntimeTurn).toHaveBeenCalledWith("turn-created");
    });
  });

  it("attaches a runtime-session deep link to a chat thread", async () => {
    const runtimeThread = thread("thread-runtime", "session-runtime", {
      agent_label: "Researcher",
      title: "Runtime notes",
    });
    vi.mocked(createThread).mockResolvedValueOnce({ thread: runtimeThread, threads: [runtimeThread] });
    const element = await renderApp({ runtimeThreads: [] as ChatThread[], runtimeThreadsLoaded: true });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });

    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          data: {
            type: "maverick.app.navigate",
            app_id: "chat",
            params: {
              app_page: "runtime-sessions/session-runtime",
              agent_label: "Researcher",
              thread_title: "Runtime notes",
            },
          },
        }),
      );
    });

    await waitForAssertion(() => {
      expect(createThread).toHaveBeenCalledWith("session-runtime", null, {
        agent_label: "Researcher",
        agent_type_id: "",
        agent_role_id: "",
        source_app_id: "chat",
        title: "Runtime notes",
      });
    });
  });

  it("does not attach a scoped runtime-session deep link in the unscoped app", async () => {
    const element = await renderApp({ runtimeThreads: [] as ChatThread[], runtimeThreadsLoaded: true });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("How can I help today?");
    });

    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          data: {
            type: "maverick.app.navigate",
            app_id: "chat",
            navigation_scope: "floating-window",
            params: { app_page: "runtime-sessions/scoped-session" },
          },
        }),
      );
    });

    expect(createThread).not.toHaveBeenCalled();
  });

  it("ignores a repeated runtime-session deep link after the session is attached", async () => {
    const runtimeThread = thread("thread-runtime", "session-runtime");
    vi.mocked(createThread).mockResolvedValue({ thread: runtimeThread, threads: [runtimeThread] });
    await renderApp({ runtimeThreads: [] as ChatThread[], runtimeThreadsLoaded: true });

    const runtimeSessionNavigate = () =>
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          data: {
            type: "maverick.app.navigate",
            app_id: "chat",
            params: { app_page: "runtime-sessions/session-runtime" },
          },
        }),
      );

    await act(async () => {
      runtimeSessionNavigate();
    });
    await waitForAssertion(() => {
      expect(createThread).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      runtimeSessionNavigate();
    });
    await waitForAssertion(() => {
      expect(createThread).toHaveBeenCalledTimes(1);
    });
  });
});

describe("App shell message scope", () => {
  it("ignores scoped capture-area messages in the unscoped main app", async () => {
    const element = await renderApp({ runtimeThreads: [] as ChatThread[], runtimeThreadsLoaded: true });
    const file = new File(["capture"], "capture.txt", { type: "text/plain" });

    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          data: {
            type: "maverick.widget.capture-area.complete",
            navigation_scope: "floating-window",
            files: [file],
          },
        }),
      );
    });

    expect(element.textContent).not.toContain("capture.txt");

    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          data: {
            type: "maverick.widget.capture-area.complete",
            files: [file],
          },
        }),
      );
    });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("capture.txt");
    });
  });
});
