/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { transcribeSpeech } from "../api/client";
import { ComposerDictationButton } from "./ComposerDictationButton";

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status = 500;
  },
  transcribeSpeech: vi.fn(),
}));

class MockMediaRecorder {
  static stopCalls = 0;
  static isTypeSupported = vi.fn(() => true);

  mimeType = "audio/webm";
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onstop: (() => void) | null = null;
  state: RecordingState = "inactive";

  constructor() {
    this.state = "inactive";
  }

  start() {
    this.state = "recording";
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) } as BlobEvent);
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
    MockMediaRecorder.stopCalls = 0;
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
    vi.mocked(transcribeSpeech).mockResolvedValue({ language: "en", language_probability: 0.9, text: "hello" });
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
    });

    expect(MockMediaRecorder.stopCalls).toBe(1);
  });
});
