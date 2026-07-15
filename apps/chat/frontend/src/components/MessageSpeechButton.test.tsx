/**
 * @vitest-environment happy-dom
 */
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { recordSpeechPlaybackMetrics, synthesizeSpeech, synthesizeSpeechStream } from "../api/client";
import { speechChunks, speechLanguageHint, speechLanguageTextFromMarkdown, speechTextFromMarkdown } from "../lib/messageSpeech";
import * as speechPcmPlayback from "../lib/speechPcmPlayback";
import { MessageSpeechButton } from "./MessageSpeechButton";

vi.mock("../api/client", () => ({
  recordSpeechPlaybackMetrics: vi.fn(async () => ({})),
  synthesizeSpeech: vi.fn(),
  synthesizeSpeechStream: vi.fn(),
}));

let container: HTMLDivElement | null = null;
let root: Root | null = null;

afterEach(() => {
  vi.mocked(synthesizeSpeech).mockReset();
  vi.mocked(synthesizeSpeechStream).mockReset();
  vi.mocked(recordSpeechPlaybackMetrics).mockClear();
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

    expect(synthesizeSpeech).toHaveBeenCalledWith("speech", "Agent response", expect.objectContaining({ signal: expect.any(AbortSignal) }));
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

  it("uses the PCM stream when both Speech and the browser advertise support", async () => {
    let onPlaying: (() => void) | undefined;
    const fakePlayer = {
      append: vi.fn(),
      decoder: { sourceSampleRate: 24000 },
      finish: vi.fn(async () => onPlaying?.()),
      started: false,
      stop: vi.fn(),
      underrunCount: 0,
    };
    vi.spyOn(speechPcmPlayback, "supportsPcmStreamingPlayback").mockReturnValue(true);
    vi.spyOn(speechPcmPlayback.PcmStreamPlayer, "create").mockImplementation(async (options) => {
      onPlaying = options.onPlaying;
      return fakePlayer as unknown as speechPcmPlayback.PcmStreamPlayer;
    });
    vi.mocked(synthesizeSpeechStream).mockResolvedValue(
      new Response(new Uint8Array([0, 0, 1, 0]), {
        status: 200,
        headers: {
          "Content-Type": "audio/pcm",
          "X-Audio-Channels": "1",
          "X-Audio-Sample-Format": "s16le",
          "X-Audio-Sample-Rate": "24000",
          "X-Generation-Id": "gen_component",
        },
      }),
    );
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<SpeechButtonHost providerStreamingSupported />);
    });
    await act(async () => {
      container?.querySelector("button")?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(synthesizeSpeechStream).toHaveBeenCalledWith(
      "speech",
      "Agent response",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(fakePlayer.append).toHaveBeenCalled();
    expect(fakePlayer.finish).toHaveBeenCalled();
    expect(fakePlayer.stop).toHaveBeenCalled();
    expect(synthesizeSpeech).not.toHaveBeenCalled();
    expect(recordSpeechPlaybackMetrics).toHaveBeenCalledWith(
      "speech",
      expect.objectContaining({ mode: "pcm-stream", outcome: "playing", playback_id: expect.any(String) }),
    );
    expect(recordSpeechPlaybackMetrics).toHaveBeenCalledWith(
      "speech",
      expect.objectContaining({ mode: "pcm-stream", outcome: "completed", generation_id: "gen_component" }),
    );
  });

  it("prioritizes the first PCM chunk before starting stream prefetch", async () => {
    const fakePlayer = {
      append: vi.fn(),
      decoder: { sourceSampleRate: 24000 },
      finish: vi.fn(async () => undefined),
      started: false,
      stop: vi.fn(),
      underrunCount: 0,
    };
    vi.spyOn(speechPcmPlayback, "supportsPcmStreamingPlayback").mockReturnValue(true);
    vi.spyOn(speechPcmPlayback.PcmStreamPlayer, "create").mockResolvedValue(
      fakePlayer as unknown as speechPcmPlayback.PcmStreamPlayer,
    );
    let resolveFirstResponse: ((response: Response) => void) | undefined;
    vi.mocked(synthesizeSpeechStream).mockImplementationOnce(
      () => new Promise<Response>((resolve) => {
        resolveFirstResponse = resolve;
      }),
    );
    vi.mocked(synthesizeSpeechStream).mockImplementation(() => new Promise<Response>(() => undefined));
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<PrefetchSpeechButtonHost providerStreamingSupported />);
    });
    const button = container.querySelector("button");
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    expect(synthesizeSpeechStream).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveFirstResponse?.(pcmResponse());
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(synthesizeSpeechStream).toHaveBeenCalledTimes(3);

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
  });

  it("aborts pending synthesis when playback is stopped", async () => {
    let requestSignal: AbortSignal | undefined;
    vi.mocked(synthesizeSpeech).mockImplementation((_providerAppId, _text, options) => {
      requestSignal = options?.signal;
      return new Promise(() => undefined);
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<SpeechButtonHost />);
    });

    const button = container.querySelector("button");
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    expect(requestSignal?.aborted).toBe(false);

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    expect(requestSignal?.aborted).toBe(true);
    expect(button?.getAttribute("aria-label")).toBe("Read response aloud");
  });

  it("passes an Italian language hint inferred from the full response to every speech chunk", async () => {
    installAudioMock({ endDuringPlay: true });
    installObjectUrlMock();
    vi.mocked(synthesizeSpeech).mockResolvedValue({ audio_base64: "UklGRg==", content_type: "audio/wav" });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    const content = [
      "Fix applicato e verificato. Ho cambiato core/api/provider_api.py e provider_config.",
      "Dopo il restart la rotta reale risponde correttamente e non restano processi appesi.",
    ].join(" ");

    await act(async () => {
      root?.render(
        <MessageSpeechButton
          activeMessageId={null}
          content={content}
          maxTextChars={90}
          messageId="agent-1"
          onActiveMessageChange={() => null}
          providerAppId="speech"
        />,
      );
    });

    const button = container.querySelector("button");
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      for (let index = 0; index < 4; index += 1) {
        await Promise.resolve();
      }
    });

    expect(synthesizeSpeech).toHaveBeenCalledTimes(2);
    expect(vi.mocked(synthesizeSpeech).mock.calls.every((call) => call[2]?.language === "it")).toBe(true);
  });

  it("surfaces audio playback failures instead of staying in loading state", async () => {
    installObjectUrlMock();
    installAudioMock({ playError: new Error("decode failed") });
    vi.mocked(synthesizeSpeech).mockResolvedValue({ audio_base64: "UklGRg==", content_type: "audio/wav" });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<SpeechButtonHost />);
    });

    const button = container.querySelector("button");
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    expect(button?.getAttribute("aria-label")).toBe("Read response aloud");
    expect(button?.title).toBe("Speech playback failed: decode failed");
    expect(container.querySelector('[role="alert"]')?.textContent).toBe("Speech playback failed: decode failed");
    expect(button?.textContent?.trim()).toBe("volume_up");
  });

  it("shows backend synthesis failures inline with provider detail", async () => {
    const error = new Error("Kokoro OpenRouter synthesis failed with HTTP 400.");
    error.name = "ApiError";
    vi.mocked(synthesizeSpeech).mockRejectedValue(error);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<SpeechButtonHost />);
    });

    const button = container.querySelector("button");
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    expect(button?.title).toBe("Speech synthesis failed: Kokoro OpenRouter synthesis failed with HTTP 400.");
    expect(container.querySelector('[role="alert"]')?.textContent).toBe(
      "Speech synthesis failed: Kokoro OpenRouter synthesis failed with HTTP 400.",
    );
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

    expect(synthesizeSpeech).toHaveBeenCalledWith("speech", "First response", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(synthesizeSpeech).toHaveBeenCalledWith("speech", "Second response", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(audioMock.instances[0]?.pause).toHaveBeenCalled();
    expect(buttons[0]?.getAttribute("aria-label")).toBe("Read response aloud");
    expect(buttons[1]?.getAttribute("aria-label")).toBe("Stop reading response");
  });

  it("splits long response speech into provider-sized synthesis requests", async () => {
    const audioMock = installAudioMock();
    vi.mocked(synthesizeSpeech).mockResolvedValue({ audio_data_url: "data:audio/wav;base64,UklGRg==", content_type: "audio/wav" });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <MessageSpeechButton
          activeMessageId={null}
          content="First sentence. Second sentence."
          maxTextChars={16}
          messageId="agent-1"
          onActiveMessageChange={() => null}
          providerAppId="speech"
        />,
      );
    });

    const button = container.querySelector("button") as HTMLButtonElement | null;
    expect(button?.getAttribute("aria-label")).toBe("Read response aloud");

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    expect(synthesizeSpeech).toHaveBeenCalledWith("speech", "First sentence.", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    for (let attempt = 0; attempt < 5 && !audioMock.instances[0]?.onended; attempt += 1) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    }
    expect(synthesizeSpeech).toHaveBeenCalledWith("speech", "Second sentence.", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(audioMock.instances[0]?.onended).toBeTruthy();
    await act(async () => {
      audioMock.instances[0]?.onended?.();
      await Promise.resolve();
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  });

  it("limits synthesis prefetch to two ordered chunks", async () => {
    installAudioMock();
    const pending = [deferredSpeechResult(), deferredSpeechResult(), deferredSpeechResult()];
    let requestIndex = 0;
    vi.mocked(synthesizeSpeech).mockImplementation(() => pending[requestIndex++].promise);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<PrefetchSpeechButtonHost />);
    });

    const button = container.querySelector("button");
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    expect(synthesizeSpeech).toHaveBeenCalledTimes(2);

    await act(async () => {
      pending[0].resolve({ audio_data_url: "data:audio/wav;base64,UklGRg==", content_type: "audio/wav" });
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(synthesizeSpeech).toHaveBeenCalledTimes(3);

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
  });

  it("keeps chunk playback moving when a short audio clip ends immediately after play starts", async () => {
    installAudioMock({ endDuringPlay: true });
    vi.mocked(synthesizeSpeech).mockResolvedValue({ audio_data_url: "data:audio/wav;base64,UklGRg==", content_type: "audio/wav" });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <MessageSpeechButton
          activeMessageId={null}
          content="First sentence. Second sentence."
          maxTextChars={16}
          messageId="agent-1"
          onActiveMessageChange={() => null}
          providerAppId="speech"
        />,
      );
    });

    const button = container.querySelector("button") as HTMLButtonElement | null;
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(synthesizeSpeech).toHaveBeenCalledWith("speech", "First sentence.", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(synthesizeSpeech).toHaveBeenCalledWith("speech", "Second sentence.", expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("splits and retries a chunk when synthesized audio exceeds the backend response limit", async () => {
    installAudioMock({ endDuringPlay: true });
    const longChunk = "Alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima. ".repeat(4).trim();
    let rejectedLongChunk = false;
    vi.mocked(synthesizeSpeech).mockImplementation((_providerAppId, text) => {
      if (text.length > 120 && !rejectedLongChunk) {
        rejectedLongChunk = true;
        return Promise.reject(new Error("Synthesized audio exceeds the response size limit."));
      }
      return Promise.resolve({ audio_data_url: "data:audio/wav;base64,UklGRg==", content_type: "audio/wav" });
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <MessageSpeechButton
          activeMessageId={null}
          content={longChunk}
          messageId="agent-1"
          onActiveMessageChange={() => null}
          providerAppId="speech"
        />,
      );
    });

    const button = container.querySelector("button") as HTMLButtonElement | null;
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      for (let index = 0; index < 4; index += 1) {
        await Promise.resolve();
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
    });

    expect(synthesizeSpeech).toHaveBeenCalledTimes(4);
    const failedChunk = String(vi.mocked(synthesizeSpeech).mock.calls[1]?.[1] || "");
    expect(failedChunk.length).toBeGreaterThan(120);
    expect(String(vi.mocked(synthesizeSpeech).mock.calls[2]?.[1] || "").length).toBeLessThan(failedChunk.length);
    expect(String(vi.mocked(synthesizeSpeech).mock.calls[3]?.[1] || "").length).toBeLessThan(failedChunk.length);
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

  it("disables response speech when only a diagnostic TTS engine is configured", async () => {
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
          providerQualityProfile="diagnostic"
        />,
      );
    });

    const button = container.querySelector("button") as HTMLButtonElement | null;
    expect(button?.getAttribute("aria-label")).toBe("Natural speech voice unavailable");
    expect(button?.title).toBe("Only a diagnostic speech engine is configured");
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
    ).toBe(["Result", "", "Open report", "", "Name Value", "", "Total 42"].join("\n"));
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

  it("keeps synthesized speech chunks within the provider text limit", () => {
    expect(speechChunks("One short sentence. Another short sentence.", 24)).toEqual(["One short sentence.", "Another short sentence."]);
    expect(speechChunks("supercalifragilistic", 8)).toEqual(["supercal", "ifragili", "stic"]);
    const chunks = speechChunks(`${"word ".repeat(180)}done`, 1500);
    expect(chunks[0].length).toBeLessThanOrEqual(180);
    expect(chunks.every((chunk) => chunk.length <= 450)).toBe(true);
  });

  it("uses a short initial chunk for medium responses", () => {
    const text = "Questa risposta deve iniziare rapidamente e poi continuare senza pause percepibili. ".repeat(4).trim();
    expect(text.length).toBeGreaterThan(180);
    expect(text.length).toBeLessThanOrEqual(450);

    const chunks = speechChunks(text);

    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks[0].length).toBeLessThanOrEqual(120);
    expect(chunks.join(" ")).toBe(text);
  });

  it("infers Italian speech language from a technical Italian response", () => {
    expect(
      speechLanguageHint(
        "Fix applicato e verificato. Ho cambiato core/api/provider_api.py. Dopo il restart la rotta reale risponde correttamente.",
      ),
    ).toBe("it");
    expect(speechLanguageHint("Ho ridotto la latenza iniziale e ora parte subito.")).toBe("it");
    expect(speechLanguageHint("La lettura deve partire subito e usare una pronuncia corretta.")).toBe("it");
    expect(
      speechLanguageHint(
        speechLanguageTextFromMarkdown("La lettura deve partire subito. `the message response speech`\n```ts\nconst voice = 'english';\n```"),
      ),
    ).toBe("it");
    expect(speechLanguageHint("Implemented and verified the provider_config update. The route now responds correctly.")).toBe("");
  });
});

function SpeechButtonHost({ providerStreamingSupported = false }: { providerStreamingSupported?: boolean } = {}) {
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);

  return (
    <MessageSpeechButton
      activeMessageId={activeMessageId}
      content="Agent response"
      messageId="agent-1"
      onActiveMessageChange={setActiveMessageId}
      providerAppId="speech"
      providerStreamingSupported={providerStreamingSupported}
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

function PrefetchSpeechButtonHost({ providerStreamingSupported = false }: { providerStreamingSupported?: boolean } = {}) {
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  return (
    <MessageSpeechButton
      activeMessageId={activeMessageId}
      content="First sentence. Second sentence. Third sentence."
      maxTextChars={16}
      messageId="agent-1"
      onActiveMessageChange={setActiveMessageId}
      providerAppId="speech"
      providerStreamingSupported={providerStreamingSupported}
    />
  );
}

function pcmResponse(): Response {
  return new Response(new Uint8Array([0, 0, 1, 0]), {
    status: 200,
    headers: {
      "Content-Type": "audio/pcm",
      "X-Audio-Channels": "1",
      "X-Audio-Sample-Format": "s16le",
      "X-Audio-Sample-Rate": "24000",
    },
  });
}

function installAudioMock(options: { endDuringPlay?: boolean; playError?: Error } = {}) {
  const instances: Array<{ src: string; play: ReturnType<typeof vi.fn>; pause: ReturnType<typeof vi.fn>; onended: (() => void) | null; onerror: (() => void) | null }> = [];
  class MockAudio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    pause = vi.fn();
    play = vi.fn(async () => {
      if (options.playError) {
        throw options.playError;
      }
      if (options.endDuringPlay) {
        this.onended?.();
      }
    });
    preload = "";
    load = vi.fn();
    setAttribute = vi.fn();
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

function deferredSpeechResult() {
  let resolve!: (value: { audio_data_url?: string; audio_base64?: string; content_type?: string }) => void;
  const promise = new Promise<{ audio_data_url?: string; audio_base64?: string; content_type?: string }>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}
