/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../api/client";
import { ChatTranscript } from "./ChatTranscript";

let container: HTMLDivElement | null = null;
let root: Root | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  vi.restoreAllMocks();
  Object.defineProperty(window, "speechSynthesis", { configurable: true, value: undefined });
  Object.defineProperty(window, "SpeechSynthesisUtterance", { configurable: true, value: undefined });
});

describe("ChatTranscript speech controls", () => {
  it("renders the speech button beside copy controls only for agent messages", async () => {
    installSpeechSynthesisMock();
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
        <ChatTranscript error={null} isLoading={false} loadingLabel="Loading" mentionItems={[]} messages={messages} />,
      );
    });

    expect(container.querySelectorAll('button[aria-label="Copy message"]').length).toBeGreaterThan(1);
    expect(container.querySelectorAll('button[aria-label="Read response aloud"]')).toHaveLength(1);
  });

  it("reads the visible collapsed Markdown text instead of the raw message source", async () => {
    const speechMock = installSpeechSynthesisMock();
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
        <ChatTranscript error={null} isLoading={false} loadingLabel="Loading" mentionItems={[]} messages={messages} />,
      );
    });

    await act(async () => {
      host.querySelector('button[aria-label="Read response aloud"]')?.dispatchEvent(
        new MouseEvent("click", { bubbles: true, cancelable: true }),
      );
    });

    const utterance = speechMock.speak.mock.calls[0]?.[0] as MockSpeechSynthesisUtterance | undefined;
    expect(utterance?.text.startsWith("Visible report")).toBe(true);
    expect(utterance?.text).toContain("...");
    expect(utterance?.text).not.toContain("https://example.test/report");
    expect(utterance?.text).not.toContain("HIDDEN_TAIL");
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

class MockSpeechSynthesisUtterance {
  lang = "";
  onboundary: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onstart: (() => void) | null = null;
  pitch = 1;
  rate = 1;
  text = "";
  voice: SpeechSynthesisVoice | null = null;
  volume = 1;
}

function installSpeechSynthesisMock() {
  let currentUtterance: MockSpeechSynthesisUtterance | null = null;
  const speechMock = {
    addEventListener: vi.fn(),
    cancel: vi.fn(() => {
      const utterance = currentUtterance;
      currentUtterance = null;
      speechMock.speaking = false;
      utterance?.onend?.();
    }),
    getVoices: vi.fn(() => []),
    paused: false,
    pause: vi.fn(),
    removeEventListener: vi.fn(),
    resume: vi.fn(),
    speak: vi.fn((utterance: MockSpeechSynthesisUtterance) => {
      currentUtterance = utterance;
      speechMock.speaking = true;
      utterance.onstart?.();
    }),
    speaking: false,
  };

  Object.defineProperty(window, "SpeechSynthesisUtterance", {
    configurable: true,
    value: MockSpeechSynthesisUtterance,
  });
  Object.defineProperty(window, "speechSynthesis", {
    configurable: true,
    value: speechMock,
  });

  return speechMock;
}
