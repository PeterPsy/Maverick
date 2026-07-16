/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { transcribeSpeech, transcribeSpeechBlob } from "../api/client";
import { ComposerDictationButton } from "./ComposerDictationButton";

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status = 500;
  },
  transcribeSpeech: vi.fn(),
  transcribeSpeechBlob: vi.fn(),
}));

class MockMediaRecorder {
  static instances: MockMediaRecorder[] = [];
  static stopCalls = 0;
  static startTimeslices: Array<number | undefined> = [];
  static isTypeSupported = vi.fn(() => true);

  mimeType = "audio/webm";
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onstop: (() => void) | null = null;
  state: RecordingState = "inactive";

  constructor() {
    this.state = "inactive";
    MockMediaRecorder.instances.push(this);
  }

  start(timeslice?: number) {
    MockMediaRecorder.startTimeslices.push(timeslice);
    this.state = "recording";
    this.emit("audio");
  }

  emit(data: string) {
    this.ondataavailable?.({ data: new Blob([data], { type: "audio/webm" }) } as BlobEvent);
  }

  stop() {
    if (this.state === "inactive") {
      throw new DOMException("Recorder is inactive.", "InvalidStateError");
    }
    MockMediaRecorder.stopCalls += 1;
    this.state = "inactive";
    this.onstop?.();
  }
}

describe("ComposerDictationButton", () => {
  let container: HTMLDivElement;
  let root: Root;
  let originalMediaRecorder: typeof MediaRecorder | undefined;
  let originalGetUserMedia: typeof navigator.mediaDevices.getUserMedia | undefined;
  let originalIsSecureContext: boolean | undefined;

  beforeEach(() => {
    MockMediaRecorder.instances = [];
    MockMediaRecorder.stopCalls = 0;
    MockMediaRecorder.startTimeslices = [];
    originalMediaRecorder = globalThis.MediaRecorder;
    originalGetUserMedia = navigator.mediaDevices?.getUserMedia;
    originalIsSecureContext = window.isSecureContext;
    globalThis.MediaRecorder = MockMediaRecorder as unknown as typeof MediaRecorder;
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
    });
    vi.mocked(transcribeSpeech).mockResolvedValue({ chunk_text: "", language: "en", language_probability: 0.9, text: "" });
    vi.mocked(transcribeSpeechBlob).mockResolvedValue({ language: "en", language_probability: 0.9, text: "hello" });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    globalThis.MediaRecorder = originalMediaRecorder as typeof MediaRecorder;
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: originalIsSecureContext });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: originalGetUserMedia ? { getUserMedia: originalGetUserMedia } : undefined,
    });
    vi.clearAllMocks();
  });

  it("ignores duplicate stop attempts when the recorder is already inactive", async () => {
    const onError = vi.fn();
    const onTranscript = vi.fn();

    await act(async () => {
      root.render(
        <ComposerDictationButton
          chunkedDictationSupported
          disabled={false}
          onError={onError}
          onTranscript={onTranscript}
          providerAppId="speech"
          providerAvailable
          supportedContentTypes={["audio/webm"]}
        />,
      );
    });

    const button = container.querySelector("button");
    expect(button).not.toBeNull();

    await act(async () => {
      button?.click();
      await Promise.resolve();
    });

    expect(container.querySelector("button")?.getAttribute("aria-label")).toBe("Stop dictation");

    await act(async () => {
      button?.click();
      button?.click();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(MockMediaRecorder.stopCalls).toBe(1);
    expect(MockMediaRecorder.startTimeslices).toEqual([1500]);
    expect(transcribeSpeechBlob).toHaveBeenCalledWith(
      "speech",
      expect.any(Blob),
      expect.objectContaining({ chunkIndex: 0, dictation: true, language: undefined, profile: "fast", sessionId: expect.any(String) }),
    );
    const firstOptions = (vi.mocked(transcribeSpeechBlob).mock.calls[0]?.[2] || {}) as { sessionId?: string };
    expect(transcribeSpeech).toHaveBeenCalledWith(
      "speech",
      "",
      "audio/webm",
      expect.objectContaining({ chunkIndex: 1, dictation: true, final: true, profile: "fast", sessionId: firstOptions.sessionId }),
    );
  });

  it("streams microphone chunks through one transcription session", async () => {
    const onError = vi.fn();
    const onTranscript = vi.fn();
    vi.mocked(transcribeSpeechBlob)
      .mockResolvedValueOnce({ chunk_text: "first", language: "en", language_probability: 0.9, text: "first" })
      .mockResolvedValueOnce({ chunk_text: "second", language: "en", language_probability: 0.9, text: "first second" });

    await act(async () => {
      root.render(
        <ComposerDictationButton
          chunkedDictationSupported
          disabled={false}
          onError={onError}
          onTranscript={onTranscript}
          providerAppId="speech"
          providerAvailable
          supportedContentTypes={["audio/webm"]}
        />,
      );
    });

    const button = container.querySelector("button");
    await act(async () => {
      button?.click();
      await Promise.resolve();
    });
    await act(async () => {
      MockMediaRecorder.instances[0]?.emit("more audio");
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(transcribeSpeechBlob).toHaveBeenCalledTimes(2);
    const firstOptions = (vi.mocked(transcribeSpeechBlob).mock.calls[0]?.[2] || {}) as { sessionId?: string };
    const secondOptions = (vi.mocked(transcribeSpeechBlob).mock.calls[1]?.[2] || {}) as {
      chunkIndex?: number;
      dictation?: boolean;
      profile?: string;
      sessionId?: string;
    };
    expect(secondOptions).toMatchObject({ chunkIndex: 1, dictation: true, profile: "fast", sessionId: firstOptions.sessionId });
    expect(onTranscript).toHaveBeenCalledWith("first", expect.objectContaining({ chunk_text: "first" }));
    expect(onTranscript).toHaveBeenCalledWith("second", expect.objectContaining({ chunk_text: "second" }));
  });

  it("collapses the voice meter while showing the animated stop indicator during transcription", async () => {
    const onError = vi.fn();
    const onTranscript = vi.fn();
    let resolveTranscription: ((value: { language: string; language_probability: number; text: string }) => void) | null = null;
    vi.mocked(transcribeSpeechBlob).mockReturnValue(
      new Promise((resolve) => {
        resolveTranscription = resolve;
      }),
    );

    await act(async () => {
      root.render(
        <ComposerDictationButton
          disabled={false}
          onError={onError}
          onTranscript={onTranscript}
          providerAppId="speech"
          providerAvailable
          supportedContentTypes={["audio/webm"]}
        />,
      );
    });

    const button = container.querySelector("button");
    await act(async () => {
      button?.click();
      await Promise.resolve();
    });

    expect(container.querySelector(".chatapp-voice-input__meter")).not.toBeNull();
    expect(container.querySelector(".chatapp-voice-input__stop-shape")).not.toBeNull();

    await act(async () => {
      button?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    const transcribingButton = container.querySelector("button");
    expect(transcribingButton?.getAttribute("aria-label")).toBe("Transcribing");
    expect(transcribingButton?.getAttribute("aria-busy")).toBe("true");
    expect(transcribingButton?.getAttribute("aria-pressed")).toBe("false");
    expect(container.querySelector(".chatapp-voice-input__meter")).toBeNull();
    expect(container.querySelector(".chatapp-voice-input__stop-shape")).not.toBeNull();

    await act(async () => {
      resolveTranscription?.({ language: "en", language_probability: 0.9, text: "done" });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.querySelector("button")?.getAttribute("aria-label")).toBe("Dictate");
    expect(onTranscript).toHaveBeenCalledWith("done", expect.objectContaining({ text: "done" }));
    expect(onError).not.toHaveBeenCalledWith(expect.any(String));
  });

  it("falls back to one-shot dictation when chunked sessions are not supported", async () => {
    const onError = vi.fn();
    const onTranscript = vi.fn();
    vi.mocked(transcribeSpeechBlob).mockResolvedValue({ language: "en", language_probability: 0.9, text: "one shot" });

    await act(async () => {
      root.render(
        <ComposerDictationButton
          disabled={false}
          onError={onError}
          onTranscript={onTranscript}
          providerAppId="speech"
          providerAvailable
          supportedContentTypes={["audio/webm"]}
        />,
      );
    });

    const button = container.querySelector("button");
    await act(async () => {
      button?.click();
      await Promise.resolve();
    });
    await act(async () => {
      button?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(MockMediaRecorder.startTimeslices).toEqual([undefined]);
    expect(transcribeSpeechBlob).toHaveBeenCalledTimes(1);
    const options = vi.mocked(transcribeSpeechBlob).mock.calls[0]?.[2] as Record<string, unknown>;
    expect(options).toMatchObject({ dictation: true, language: undefined, profile: "fast" });
    expect(options).not.toHaveProperty("sessionId");
    expect(options).not.toHaveProperty("chunkIndex");
    expect(onTranscript).toHaveBeenCalledWith(
      "one shot",
      expect.objectContaining({
        metrics: expect.objectContaining({
          client_stop_to_insert_seconds: expect.any(Number),
          client_stop_to_text_seconds: expect.any(Number),
        }),
        text: "one shot",
      }),
    );
  });

  it("allows one-shot recordings larger than the old 700 KB cap", async () => {
    const onError = vi.fn();
    const onTranscript = vi.fn();
    vi.mocked(transcribeSpeechBlob).mockResolvedValue({ language: "en", language_probability: 0.9, text: "longer recording" });

    await act(async () => {
      root.render(
        <ComposerDictationButton
          disabled={false}
          onError={onError}
          onTranscript={onTranscript}
          providerAppId="speech"
          providerAvailable
          supportedContentTypes={["audio/webm"]}
        />,
      );
    });

    const button = container.querySelector("button");
    await act(async () => {
      button?.click();
      await Promise.resolve();
    });
    await act(async () => {
      MockMediaRecorder.instances[0]?.emit("x".repeat(700_001));
      button?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(transcribeSpeechBlob).toHaveBeenCalledTimes(1);
    expect((vi.mocked(transcribeSpeechBlob).mock.calls[0]?.[1] as Blob).size).toBeGreaterThan(700_000);
    expect(onError).not.toHaveBeenCalledWith(expect.stringContaining("700 KB"));
    expect(onTranscript).toHaveBeenCalledWith("longer recording", expect.objectContaining({ text: "longer recording" }));
  });

  it("keeps a chunk transcription error instead of replacing it with no speech", async () => {
    const onError = vi.fn();
    const onTranscript = vi.fn();
    vi.mocked(transcribeSpeechBlob).mockRejectedValue(new Error("backend unavailable"));

    await act(async () => {
      root.render(
        <ComposerDictationButton
          chunkedDictationSupported
          disabled={false}
          onError={onError}
          onTranscript={onTranscript}
          providerAppId="speech"
          providerAvailable
          supportedContentTypes={["audio/webm"]}
        />,
      );
    });

    const button = container.querySelector("button");
    await act(async () => {
      button?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(onTranscript).not.toHaveBeenCalled();
    expect(onError).toHaveBeenLastCalledWith("Unable to transcribe microphone audio: backend unavailable");
    expect(onError).not.toHaveBeenCalledWith("No speech detected.");
  });

  it("does not insert full streaming text when chunk text is empty", async () => {
    const onError = vi.fn();
    const onTranscript = vi.fn();
    vi.mocked(transcribeSpeechBlob).mockResolvedValue({ chunk_text: "", language: "en", language_probability: 0.9, text: "partial full text" });

    await act(async () => {
      root.render(
        <ComposerDictationButton
          chunkedDictationSupported
          disabled={false}
          onError={onError}
          onTranscript={onTranscript}
          providerAppId="speech"
          providerAvailable
          supportedContentTypes={["audio/webm"]}
        />,
      );
    });

    const button = container.querySelector("button");
    await act(async () => {
      button?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(onTranscript).not.toHaveBeenCalled();
  });
});
