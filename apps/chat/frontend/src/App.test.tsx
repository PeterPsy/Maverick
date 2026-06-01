/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import {
  createThread,
  getAgentDefinition,
  getAppDependencies,
  getSpeechCapabilities,
  listAgentCatalog,
  listApps,
  listProviders,
  listSkills,
  previewAgentPrompt,
} from "./api/client";
import type { AgentTypeSummary, AppDependenciesPayload, ChatThread } from "./api/client";
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

vi.mock("./api/client", () => ({
  createRuntimeSessionWithTurn: vi.fn(),
  createThread: vi.fn(),
  getAgentDefinition: vi.fn(),
  getAppDependencies: vi.fn(),
  getSpeechCapabilities: vi.fn(),
  getWidgetContext: vi.fn(),
  interruptRuntimeTurn: vi.fn(),
  isRuntimeSessionUnavailableError: vi.fn(() => false),
  listAgentCatalog: vi.fn(),
  listApps: vi.fn(),
  listProviders: vi.fn(),
  listSkills: vi.fn(),
  markThreadRead: vi.fn(),
  orderChatThreads: vi.fn((threads: unknown[]) => threads),
  previewAgentPrompt: vi.fn(),
  selectProvider: vi.fn(),
  selectedDependencyProviderAppId: (payload: AppDependenciesPayload, alias: string) =>
    payload.dependencies.find((dependency) => dependency.alias === alias)?.selected_provider_app_ids[0] || "",
  selectedSharedDependencyProviderAppId: (payload: AppDependenciesPayload, aliases: string[]) => {
    const providerIds = aliases.map((alias) => payload.dependencies.find((dependency) => dependency.alias === alias)?.selected_provider_app_ids[0] || "");
    return providerIds.length && providerIds.every((providerId) => providerId && providerId === providerIds[0]) ? providerIds[0] : "";
  },
  sendRuntimeTurn: vi.fn(),
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

beforeEach(() => {
  window.localStorage.clear();
  clearAgentRuntimeConfigCache();
  vi.mocked(listProviders).mockResolvedValue({
    workspace_id: "default",
    active_provider: null,
    items: [],
  });
  vi.mocked(listApps).mockResolvedValue([]);
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
  it("shows a draft with an error when a requested thread is missing", async () => {
    const element = await renderApp({ runtimeThreads: [] as ChatThread[], runtimeThreadsLoaded: true, threadId: "missing-thread" });

    await waitForAssertion(() => {
      expect(element.textContent).toContain("This chat is no longer available.");
      expect(element.querySelector('[role="textbox"]')).not.toBeNull();
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
