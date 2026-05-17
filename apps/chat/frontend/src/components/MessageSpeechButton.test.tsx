/**
 * @vitest-environment happy-dom
 */
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MessageSpeechButton, speechTextFromMarkdown } from "./MessageSpeechButton";

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

describe("MessageSpeechButton", () => {
  it("does not render when browser speech synthesis is unavailable", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <MessageSpeechButton activeMessageId={null} content="Agent response" messageId="agent-1" onActiveMessageChange={() => null} />,
      );
    });

    expect(container.querySelector("button")).toBeNull();
  });

  it("starts and stops reading the agent message content", async () => {
    const speechMock = installSpeechSynthesisMock();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<SpeechButtonHost />);
    });

    const button = container.querySelector("button");
    expect(button?.getAttribute("aria-label")).toBe("Read response aloud");

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    const utterance = speechMock.speak.mock.calls[0]?.[0] as MockSpeechSynthesisUtterance | undefined;
    expect(utterance?.text).toBe("Agent response");
    expect(button?.getAttribute("aria-label")).toBe("Stop reading response");
    expect(button?.textContent?.trim()).toBe("stop_circle");

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    expect(speechMock.cancel).toHaveBeenCalled();
    expect(button?.getAttribute("aria-label")).toBe("Read response aloud");
    expect(button?.textContent?.trim()).toBe("volume_up");
  });

  it("stops the first message when a second message starts reading", async () => {
    const speechMock = installSpeechSynthesisMock();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<TwoSpeechButtonsHost />);
    });

    const buttons = Array.from(container.querySelectorAll("button"));
    await act(async () => {
      buttons[0]?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    await act(async () => {
      buttons[1]?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    expect(speechMock.cancel).toHaveBeenCalled();
    expect(speechMock.speak).toHaveBeenCalledTimes(2);
    expect(buttons[0]?.getAttribute("aria-label")).toBe("Read response aloud");
    expect(buttons[1]?.getAttribute("aria-label")).toBe("Stop reading response");
  });

  it("converts visible Markdown content into readable speech text", () => {
    expect(
      speechTextFromMarkdown(
        [
          "## Result",
          "",
          "[Open report](https://example.test/report) [ref:storage/file/file_123]",
          "",
          "```ts",
          "const answer = 42;",
          "```",
          "",
          "| Name | Value |",
          "| --- | --- |",
          "| Total | **42** |",
        ].join("\n"),
      ),
    ).toBe(["Result", "", "Open report", "", "const answer = 42;", "", "Name Value", "", "Total 42"].join("\n"));
  });

  it("preserves visible punctuation that is not Markdown markup", () => {
    expect(speechTextFromMarkdown("Use foo_bar, __init__, 2 * 3, path_with_underscores, and user~name.")).toBe(
      "Use foo_bar, __init__, 2 * 3, path_with_underscores, and user~name.",
    );
  });

  it("removes Markdown style delimiters only when they form conservative inline markup", () => {
    expect(speechTextFromMarkdown("Read **bold**, *italic*, ~~removed~~, __two words__, __bold__, and _italic_.")).toBe(
      "Read bold, italic, removed, two words, bold, and italic.",
    );
  });
});

function SpeechButtonHost() {
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);

  return (
    <MessageSpeechButton
      activeMessageId={activeMessageId}
      content="Agent response"
      messageId="agent-1"
      onActiveMessageChange={setActiveMessageId}
    />
  );
}

function TwoSpeechButtonsHost() {
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);

  return (
    <>
      <MessageSpeechButton
        activeMessageId={activeMessageId}
        content="First response"
        messageId="agent-1"
        onActiveMessageChange={setActiveMessageId}
      />
      <MessageSpeechButton
        activeMessageId={activeMessageId}
        content="Second response"
        messageId="agent-2"
        onActiveMessageChange={setActiveMessageId}
      />
    </>
  );
}

type SpeechHandler = (() => void) | null;

class MockSpeechSynthesisUtterance {
  lang = "";
  onboundary: SpeechHandler = null;
  onend: SpeechHandler = null;
  onerror: SpeechHandler = null;
  onstart: SpeechHandler = null;
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
