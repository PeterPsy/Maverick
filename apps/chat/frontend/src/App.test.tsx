/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { getAppDependencies, listAgentCatalog, listApps, listProviders, listSkills } from "./api/client";
import type { AgentTypeSummary, AppDependenciesPayload } from "./api/client";

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
  return {
    workspace_id: "default",
    consumer_app_id: "chat",
    status: "resolved",
    dependencies: [
      {
        alias: "agent-catalog",
        interface: "agent.catalog",
        version: "^1",
        required: false,
        cardinality: "one",
        description: "Agent catalog",
        status: selectedProviderAppIds.length ? "resolved" : "optional_unset",
        candidates: [],
        selected_provider_app_ids: selectedProviderAppIds,
        stale_provider_app_ids: [],
        blocked_reason: null,
      },
    ],
  };
}

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(listProviders).mockResolvedValue({
    workspace_id: "default",
    active_provider: null,
    items: [],
  });
  vi.mocked(listApps).mockResolvedValue([]);
  vi.mocked(listSkills).mockResolvedValue([]);
  vi.mocked(getAppDependencies).mockResolvedValue(dependencyPayload(["agents"]));
  vi.mocked(listAgentCatalog).mockResolvedValue({ agent_types: [socialVideoAgent] });
});

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  vi.clearAllMocks();
  window.localStorage.clear();
});

async function renderApp() {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root?.render(<App />);
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

describe("App agent catalog dependency refresh", () => {
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
