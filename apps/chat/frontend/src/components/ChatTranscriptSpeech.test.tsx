/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { synthesizeSpeech } from "../api/client";
import type { ChatMessage } from "../api/client";
import { ChatTranscript } from "./ChatTranscript";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    synthesizeSpeech: vi.fn(),
  };
});

let container: HTMLDivElement | null = null;
let root: Root | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("ChatTranscript speech controls", () => {
  it("renders the speech button beside copy controls only for agent messages when a provider is available", async () => {
    const messages: ChatMessage[] = [
      message("human-1", "human", "Can you summarize this?"),
      message("agent-1", "agent", "Here is the summary."),
      message("system-1", "system", "Thread restored."),
    ];
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <ChatTranscript
          error={null}
          isLoading={false}
          loadingLabel="Loading"
          mentionItems={[]}
          messages={messages}
          speechProviderAppId="speech"
        />,
      );
    });

    expect(container.querySelectorAll('button[aria-label="Copy message"]').length).toBeGreaterThan(1);
    expect(container.querySelectorAll('button[aria-label="Read response aloud"]')).toHaveLength(1);
  });

  it("keeps a disabled speech button visible when the linked provider is unavailable", async () => {
    const messages: ChatMessage[] = [message("agent-1", "agent", "Here is the summary.")];
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <ChatTranscript
          error={null}
          isLoading={false}
          loadingLabel="Loading"
          mentionItems={[]}
          messages={messages}
          speechProviderAppId="speech"
          speechProviderAvailable={false}
        />,
      );
    });

    const button = container.querySelector('button[aria-label="Speech provider unavailable"]') as HTMLButtonElement | null;
    expect(button).not.toBeNull();
    expect(button?.disabled).toBe(true);
  });

  it("sends visible collapsed Markdown text to the selected speech provider", async () => {
    installAudioMock();
    vi.mocked(synthesizeSpeech).mockResolvedValue({ audio_data_url: "data:audio/wav;base64,UklGRg==", content_type: "audio/wav" });
    const messages: ChatMessage[] = [
      message(
        "agent-1",
        "agent",
        `[Visible report](https://example.test/report)\n\n${" ".repeat(3300)}HIDDEN_TAIL`,
      ),
    ];
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const host = container;

    await act(async () => {
      root?.render(
        <ChatTranscript
          error={null}
          isLoading={false}
          loadingLabel="Loading"
          mentionItems={[]}
          messages={messages}
          speechProviderAppId="speech"
        />,
      );
    });

    await act(async () => {
      host.querySelector('button[aria-label="Read response aloud"]')?.dispatchEvent(
        new MouseEvent("click", { bubbles: true, cancelable: true }),
      );
    });

    const text = vi.mocked(synthesizeSpeech).mock.calls[0]?.[1] || "";
    expect(text.startsWith("Visible report")).toBe(true);
    expect(text).toContain("...");
    expect(text).not.toContain("https://example.test/report");
    expect(text).not.toContain("HIDDEN_TAIL");
  });
});

function message(id: string, role: ChatMessage["role"], content: string): ChatMessage {
  return {
    id,
    role,
    content,
    createdAt: "2026-05-16T12:00:00.000Z",
  };
}

function installAudioMock() {
  class MockAudio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    pause = vi.fn();
    play = vi.fn(async () => undefined);

    constructor(readonly src: string) {}
  }
  vi.stubGlobal("Audio", MockAudio);
}
