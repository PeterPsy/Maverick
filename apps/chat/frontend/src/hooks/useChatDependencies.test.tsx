/**
 * @vitest-environment happy-dom
 */
import { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getAppDependencies,
  getSpeechCapabilities,
  listAgentCatalog,
  listProviders,
  prewarmSpeechWorker,
} from "../api/client";
import type { AppDependenciesPayload } from "../api/client";
import { useChatDependencies } from "./useChatDependencies";

vi.mock("../api/client", () => ({
  getAppDependencies: vi.fn(),
  getSpeechCapabilities: vi.fn(),
  listAgentCatalog: vi.fn(),
  listProviders: vi.fn(),
  prewarmSpeechWorker: vi.fn(),
  selectedDependencyProviderAppId: (payload: AppDependenciesPayload, alias: string) =>
    payload.dependencies.find((dependency) => dependency.alias === alias)?.selected_provider_app_ids[0] || "",
  selectedSharedDependencyProviderAppId: (payload: AppDependenciesPayload, aliases: string[]) => {
    const providerIds = aliases.map((alias) => payload.dependencies.find((dependency) => dependency.alias === alias)?.selected_provider_app_ids[0] || "");
    return providerIds.length && providerIds.every((providerId) => providerId && providerId === providerIds[0]) ? providerIds[0] : "";
  },
}));

vi.mock("../lib/providerRuntimeOptions", () => ({
  providerItemsFromPayload: () => [],
}));

vi.mock("./useChatRuntimeControls", () => ({
  clearAgentRuntimeConfigCache: vi.fn(),
}));

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  vi.mocked(listProviders).mockResolvedValue({ workspace_id: "default", active_provider: null, items: [] });
  vi.mocked(getAppDependencies).mockResolvedValue(dependencyPayload());
  vi.mocked(getSpeechCapabilities).mockRejectedValue(new Error("capability denied"));
  vi.mocked(listAgentCatalog).mockResolvedValue({ agent_types: [] });
  vi.mocked(prewarmSpeechWorker).mockResolvedValue({});
});

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  vi.clearAllMocks();
});

describe("useChatDependencies", () => {
  it("keeps selected speech provider ids when capability loading fails", async () => {
    const snapshots: Array<ReturnType<typeof useChatDependencies>> = [];

    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<DependencyProbe onSnapshot={(snapshot) => snapshots.push(snapshot)} />);
    });

    await waitForAssertion(() => {
      const latest = snapshots.at(-1);
      expect(getSpeechCapabilities).toHaveBeenCalledWith("speech");
      expect(latest?.speechProviderAppId).toBe("speech");
      expect(latest?.speechProviderAvailable).toBe(false);
      expect(latest?.transcriptionProviderAppId).toBe("speech");
      expect(latest?.transcriptionProviderAvailable).toBe(false);
    });
    expect(prewarmSpeechWorker).not.toHaveBeenCalled();
  });

  it("does not enable composer chunked dictation for conversation-only streaming", async () => {
    const snapshots: Array<ReturnType<typeof useChatDependencies>> = [];
    vi.mocked(getSpeechCapabilities).mockResolvedValue({
      interfaces: {
        "speech.transcription": {
          available: true,
          provider_available: true,
          chunked_dictation_supported: true,
          conversation_streaming_supported: true,
          dictation_streaming_supported: false,
        },
      },
    });

    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<DependencyProbe onSnapshot={(snapshot) => snapshots.push(snapshot)} />);
    });

    await waitForAssertion(() => {
      expect(snapshots.at(-1)?.transcriptionProviderAvailable).toBe(true);
      expect(snapshots.at(-1)?.transcriptionChunkedDictationSupported).toBe(false);
    });
  });

  it("enables composer chunked dictation only when explicitly supported", async () => {
    const snapshots: Array<ReturnType<typeof useChatDependencies>> = [];
    vi.mocked(getSpeechCapabilities).mockResolvedValue({
      interfaces: {
        "speech.transcription": {
          available: true,
          provider_available: true,
          chunked_dictation_supported: true,
          dictation_streaming_supported: true,
        },
      },
    });

    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<DependencyProbe onSnapshot={(snapshot) => snapshots.push(snapshot)} />);
    });

    await waitForAssertion(() => {
      expect(snapshots.at(-1)?.transcriptionProviderAvailable).toBe(true);
      expect(snapshots.at(-1)?.transcriptionChunkedDictationSupported).toBe(true);
    });
  });
});

function DependencyProbe({ onSnapshot }: { onSnapshot: (snapshot: ReturnType<typeof useChatDependencies>) => void }) {
  const dependencies = useChatDependencies();
  useEffect(() => {
    onSnapshot(dependencies);
  }, [dependencies, onSnapshot]);
  useEffect(() => {
    void dependencies.loadInitialChatDependencies();
  }, []);
  return null;
}

function dependencyPayload(): AppDependenciesPayload {
  return {
    workspace_id: "default",
    consumer_app_id: "chat",
    status: "resolved",
    dependencies: [
      dependency("agent-catalog", "agent.catalog", []),
      dependency("agent-prompt-materializer", "agent.prompt-materializer", []),
      dependency("text-to-speech", "speech.synthesis", ["speech"]),
      dependency("speech-to-text", "speech.transcription", ["speech"]),
    ],
  };
}

function dependency(alias: string, interfaceName: string, selectedProviderAppIds: string[]) {
  return {
    alias,
    interface: interfaceName,
    version: "^1",
    required: false,
    cardinality: "one",
    description: alias,
    status: selectedProviderAppIds.length ? "resolved" : "optional_unset",
    candidates: [],
    selected_provider_app_ids: selectedProviderAppIds,
    stale_provider_app_ids: [],
    blocked_reason: null,
  };
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
