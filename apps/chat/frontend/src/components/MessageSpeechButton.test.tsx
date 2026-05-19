/**
 * @vitest-environment happy-dom
 */
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { synthesizeSpeech } from "../api/client";
import { MessageSpeechButton, speechTextFromMarkdown } from "./MessageSpeechButton";

vi.mock("../api/client", () => ({
  synthesizeSpeech: vi.fn(),
}));

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

describe("MessageSpeechButton", () => {
  it("does not render when no speech provider is available", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <MessageSpeechButton
          activeMessageId={null}
          content="Agent response"
          messageId="agent-1"
          onActiveMessageChange={() => null}
          providerAppId=""
        />,
      );
    });

    expect(container.querySelector("button")).toBeNull();
  });

  it("requests backend synthesis and controls audio playback", async () => {
    const audioMock = installAudioMock();
    const objectUrlMock = installObjectUrlMock();
    vi.mocked(synthesizeSpeech).mockResolvedValue({ audio_base64: "UklGRg==", content_type: "audio/wav" });
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

    expect(synthesizeSpeech).toHaveBeenCalledWith("speech", "Agent response");
    expect(objectUrlMock.createObjectURL).toHaveBeenCalled();
    expect(audioMock.instances[0]?.src).toBe("blob:speech-audio");
    expect(audioMock.instances[0]?.play).toHaveBeenCalled();
    expect(button?.getAttribute("aria-label")).toBe("Stop reading response");
    expect(button?.textContent?.trim()).toBe("stop_circle");

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    expect(audioMock.instances[0]?.pause).toHaveBeenCalled();
    expect(objectUrlMock.revokeObjectURL).toHaveBeenCalledWith("blob:speech-audio");
    expect(button?.getAttribute("aria-label")).toBe("Read response aloud");
    expect(button?.textContent?.trim()).toBe("volume_up");
  });

  it("stops the first message when a second message starts playback", async () => {
    const audioMock = installAudioMock();
    vi.mocked(synthesizeSpeech).mockResolvedValue({ audio_data_url: "data:audio/wav;base64,UklGRg==", content_type: "audio/wav" });
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

    expect(synthesizeSpeech).toHaveBeenCalledWith("speech", "First response");
    expect(synthesizeSpeech).toHaveBeenCalledWith("speech", "Second response");
    expect(audioMock.instances[0]?.pause).toHaveBeenCalled();
    expect(buttons[0]?.getAttribute("aria-label")).toBe("Read response aloud");
    expect(buttons[1]?.getAttribute("aria-label")).toBe("Stop reading response");
  });

  it("disables synthesis before calling the provider when normalized text exceeds the provider limit", async () => {
    vi.mocked(synthesizeSpeech).mockClear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <MessageSpeechButton
          activeMessageId={null}
          content={"x".repeat(1501)}
          maxTextChars={1500}
          messageId="agent-1"
          onActiveMessageChange={() => null}
          providerAppId="speech"
        />,
      );
    });

    const button = container.querySelector("button") as HTMLButtonElement | null;
    expect(button?.getAttribute("aria-label")).toBe("Read response aloud unavailable: response is too long");
    expect(button?.disabled).toBe(true);

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    expect(synthesizeSpeech).not.toHaveBeenCalled();
  });

  it("renders a disabled control instead of disappearing when the provider is linked but unavailable", async () => {
    vi.mocked(synthesizeSpeech).mockClear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <MessageSpeechButton
          activeMessageId={null}
          content="Agent response"
          messageId="agent-1"
          onActiveMessageChange={() => null}
          providerAvailable={false}
          providerAppId="speech"
        />,
      );
    });

    const button = container.querySelector("button") as HTMLButtonElement | null;
    expect(button?.getAttribute("aria-label")).toBe("Speech provider unavailable");
    expect(button?.disabled).toBe(true);
    expect(button?.textContent?.trim()).toBe("volume_off");
    expect(synthesizeSpeech).not.toHaveBeenCalled();
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
      providerAppId="speech"
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
        providerAppId="speech"
      />
      <MessageSpeechButton
        activeMessageId={activeMessageId}
        content="Second response"
        messageId="agent-2"
        onActiveMessageChange={setActiveMessageId}
        providerAppId="speech"
      />
    </>
  );
}

function installAudioMock() {
  const instances: Array<{ src: string; play: ReturnType<typeof vi.fn>; pause: ReturnType<typeof vi.fn>; onended: (() => void) | null; onerror: (() => void) | null }> = [];
  class MockAudio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    pause = vi.fn();
    play = vi.fn(async () => undefined);
    src: string;

    constructor(src: string) {
      this.src = src;
      instances.push(this);
    }
  }
  vi.stubGlobal("Audio", MockAudio);
  return { instances };
}

function installObjectUrlMock() {
  const createObjectURL = vi.fn(() => "blob:speech-audio");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL,
    revokeObjectURL,
  });
  return { createObjectURL, revokeObjectURL };
}
