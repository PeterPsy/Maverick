/** @vitest-environment happy-dom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sendRuntimeTurn, type ChatThread } from "../api/client";
import { useMessageSubmission } from "./useMessageSubmission";

vi.mock("../api/client", async (original) => ({
  ...await original<typeof import("../api/client")>(), sendRuntimeTurn: vi.fn(),
}));

const thread = { thread_id: "thread", runtime_session_id: "session", source_app_id: "chat", device_use_enabled: true } as ChatThread;
let root: Root | null = null;
let result: ReturnType<typeof useMessageSubmission>;
const setter = vi.fn();
const setComposer = vi.fn();
const setComposerError = vi.fn();

function Harness({ verify, activeThread = thread }: { verify: () => Promise<void>; activeThread?: ChatThread | null }) {
  result = useMessageSubmission({
    activeInterAgentRun: null, activeAppContext: null, activeThread, activeTurn: null,
    attachments: [], clearAttachments: setter, composer: "Riprendi il lavoro", composerMentionItems: [],
    draftChat: activeThread ? null : { draftId: "draft", projectId: null, systemPrompt: "" }, deviceUseActivationId: activeThread ? null : "draft-mac", ensureDeviceUseReady: verify, canPreloadRuntime: false,
    isBootstrapping: false, isHistoryLoading: false, isRuntimeBusy: false, multiAgentMode: "off",
    navigationScope: "test", notifyActiveThreadChanged: setter, selectedAgentRuntimeConfig: async () => null,
    setActiveSession: setter, setActiveThread: setter, setActiveTurn: setter, setComposer, setComposerError,
    setDraftChat: setter, setError: setter, setEvents: setter, setSelectedReferences: setter,
    setThreads: setter, threads: activeThread ? [activeThread] : [],
  });
  return null;
}

async function render(verify: () => Promise<void>, activeThread: ChatThread | null = thread) {
  if (!root) { const host = document.createElement("div"); document.body.append(host); root = createRoot(host); }
  await act(async () => { root?.render(<Harness verify={verify} activeThread={activeThread} />); });
}
afterEach(() => { act(() => root?.unmount()); root = null; vi.clearAllMocks(); document.body.innerHTML = ""; });

describe("Device Use submission admission", () => {
  it("preserves the unsent draft when initial Mac activation is unavailable", async () => {
    const verify = vi.fn().mockRejectedValue(new Error("Mac scollegato. Premi Full."));
    await render(verify, null);
    await act(async () => { await result.handleSend(); });
    expect(verify).toHaveBeenCalledOnce();
    expect(setComposerError).toHaveBeenCalledWith("Mac scollegato. Premi Full.");
    expect(setComposer).not.toHaveBeenCalled();
    expect(sendRuntimeTurn).not.toHaveBeenCalled();
    expect(result.pendingUserMessages).toEqual([]);
    expect(result.failedUserMessages).toEqual([]);
  });

  it("submits ordinary workspace work when the chat's Mac is disconnected", async () => {
    const verify = vi.fn().mockRejectedValue(new Error("Mac scollegato"));
    vi.mocked(sendRuntimeTurn).mockResolvedValue({ delivery: "queued" });
    await render(verify);
    await act(async () => { await result.handleSend(); });
    expect(verify).not.toHaveBeenCalled();
    expect(sendRuntimeTurn).toHaveBeenCalledOnce();
    expect(setComposerError).toHaveBeenCalledWith(null);
  });

  it("does not duplicate submission while checking a lease or send it to a newly opened chat", async () => {
    let resolve!: () => void;
    const verify = vi.fn(() => new Promise<void>((done) => { resolve = done; }));
    await render(verify, null);
    let pending!: Promise<void>;
    await act(async () => {
      pending = result.handleSend();
      await result.handleSend();
    });
    expect(verify).toHaveBeenCalledOnce();
    await render(verify, { ...thread, thread_id: "another", runtime_session_id: "other-session" });
    await act(async () => { resolve(); await pending; });
    expect(sendRuntimeTurn).not.toHaveBeenCalled();
    expect(setComposer).not.toHaveBeenCalled();
  });
});
