import type { Dispatch, SetStateAction } from "react";
import { useEffect, useRef, useState } from "react";
import { recordSpeechPlaybackMetrics, synthesizeSpeech, synthesizeSpeechStream } from "../api/client";
import {
  isSplittableSynthesisError,
  retrySpeechChunks,
  speechChunks,
  speechLanguageHint,
  speechLanguageTextFromMarkdown,
  speechTextFromMarkdown,
} from "../lib/messageSpeech";
import { audioCompletion, playAudioWithTimeout, speechPlaybackErrorMessage } from "../lib/speechAudioPlayback";
import {
  parseSpeechServerTiming,
  PcmStreamPlayer,
  publishSpeechPlaybackMetrics,
  supportsPcmStreamingPlayback,
  type SpeechPcmPlaybackMetrics,
} from "../lib/speechPcmPlayback";

const TTS_PREFETCH_CONCURRENCY = 2;

type MessageSpeechButtonProps = {
  activeMessageId: string | null;
  content: string;
  maxTextChars?: number;
  messageId: string;
  onActiveMessageChange: Dispatch<SetStateAction<string | null>>;
  providerAvailable?: boolean;
  providerAppId: string;
  providerQualityProfile?: string;
  providerStreamingSupported?: boolean;
};

type SpeechPlaybackStatus = "idle" | "loading" | "playing" | "error";
type SpeechAudioResult = { audio_data_url?: string; audio_base64?: string; content_type?: string };

export function MessageSpeechButton(props: MessageSpeechButtonProps) {
  const speechText = speechTextFromMarkdown(props.content);

  if (!speechText || !props.providerAppId) {
    return null;
  }
  if (props.providerAvailable === false) {
    const diagnosticOnly = props.providerQualityProfile === "diagnostic";
    return (
      <DisabledSpeechButton
        ariaLabel={diagnosticOnly ? "Natural speech voice unavailable" : "Speech provider unavailable"}
        title={diagnosticOnly ? "Only a diagnostic speech engine is configured" : "Speech provider unavailable"}
      />
    );
  }
  return <SupportedMessageSpeechButton {...props} speechText={speechText} />;
}

function DisabledSpeechButton({ ariaLabel, title }: { ariaLabel: string; title: string }) {
  return (
    <button
      aria-label={ariaLabel}
      className="chatapp-message-action chatapp-message-action--icon chatapp-message-action--speech is-disabled"
      disabled
      title={title}
      type="button"
    >
      <span aria-hidden="true" className="material-symbols-rounded">
        volume_off
      </span>
    </button>
  );
}

function SupportedMessageSpeechButton({
  activeMessageId,
  content,
  messageId,
  onActiveMessageChange,
  providerAppId,
  providerStreamingSupported = false,
  speechText,
  maxTextChars = 0,
}: MessageSpeechButtonProps & { speechText: string }) {
  const [status, setStatus] = useState<SpeechPlaybackStatus>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pcmPlayerRef = useRef<PcmStreamPlayer | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  const selfActivationRef = useRef(false);
  const isActive = activeMessageId === messageId;
  const isReading = isActive && (status === "loading" || status === "playing");

  useEffect(() => {
    if (isActive) {
      selfActivationRef.current = false;
      return;
    }
    if (!selfActivationRef.current && (status === "loading" || status === "playing")) {
      stopPlayback();
    }
  }, [isActive, status]);

  useEffect(() => () => stopPlayback(), []);

  async function toggleSpeech() {
    if (isReading) {
      stopPlayback();
      clearActiveMessage(onActiveMessageChange, messageId);
      return;
    }

    selfActivationRef.current = true;
    onActiveMessageChange(messageId);
    setStatus("loading");
    setErrorMessage("");
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const abortController = new AbortController();
    abortControllerRef.current?.abort();
    abortControllerRef.current = abortController;
    const chunks = speechChunks(speechText, maxTextChars);
    const language = speechLanguageHint(speechLanguageTextFromMarkdown(content));
    const tapStartedAt = nowMilliseconds();
    const playbackId = createSpeechPlaybackId();
    let playbackMode: SpeechPcmPlaybackMetrics["mode"] = "pcm-stream";

    try {
      if (providerStreamingSupported && supportsPcmStreamingPlayback()) {
        try {
          await playStreamingChunks(chunks, requestId, language, abortController.signal, tapStartedAt, playbackId);
          completePlayback(requestId);
          return;
        } catch (error) {
          const streamStarted = pcmPlayerRef.current?.started === true;
          pcmPlayerRef.current?.stop();
          pcmPlayerRef.current = null;
          if (abortController.signal.aborted || requestIdRef.current !== requestId) {
            return;
          }
          if (streamStarted) {
            throw error;
          }
        }
      }
      playbackMode = "buffered";
      let nextChunkIndex = 0;
      const prefetchedChunks = new Map<number, Promise<SpeechAudioResult[]>>();
      const requestStartedAt = nowMilliseconds();

      function fillPrefetchQueue() {
        while (nextChunkIndex < chunks.length && prefetchedChunks.size < TTS_PREFETCH_CONCURRENCY) {
          const index = nextChunkIndex;
          nextChunkIndex += 1;
          const promise = synthesizeChunkWithFallback(chunks[index], requestId, language, abortController.signal);
          void promise.catch(() => undefined);
          prefetchedChunks.set(index, promise);
        }
      }

      fillPrefetchQueue();
      let bufferedPlaybackStarted = false;
      for (let index = 0; index < chunks.length; index += 1) {
        if (requestIdRef.current !== requestId) {
          return;
        }
        setStatus(audioRef.current ? "playing" : "loading");
        const prefetched = prefetchedChunks.get(index);
        if (!prefetched) {
          throw new Error("Speech prefetch queue lost a chunk.");
        }
        const results = await prefetched;
        prefetchedChunks.delete(index);
        fillPrefetchQueue();
        for (const result of results) {
          if (requestIdRef.current !== requestId) {
            return;
          }
          await playSynthesizedChunk(result, requestId, () => {
            if (!bufferedPlaybackStarted) {
              bufferedPlaybackStarted = true;
              reportSpeechPlaybackMetrics(providerAppId, {
                mode: "buffered",
                outcome: "playing",
                playback_id: playbackId,
                tap_to_request_ms: roundedMilliseconds(requestStartedAt - tapStartedAt),
                tap_to_audio_playing_ms: roundedMilliseconds(nowMilliseconds() - tapStartedAt),
              });
            }
          });
        }
      }
      reportSpeechPlaybackMetrics(providerAppId, {
        mode: "buffered",
        outcome: "completed",
        playback_id: playbackId,
      });
      completePlayback(requestId);
    } catch (error) {
      if (requestIdRef.current === requestId) {
        reportSpeechPlaybackMetrics(providerAppId, {
          mode: playbackMode,
          outcome: abortController.signal.aborted ? "cancelled" : "failed",
          playback_id: playbackId,
          failure_code: speechPlaybackFailureCode(error),
        });
        failPlayback(requestId, speechPlaybackErrorMessage(error));
      }
    }
  }

  async function playStreamingChunks(
    chunks: string[],
    requestId: number,
    language: string,
    signal: AbortSignal,
    tapStartedAt: number,
    playbackId: string,
  ) {
    let nextChunkIndex = 0;
    const prefetchedChunks = new Map<number, Promise<Response[]>>();
    const metrics: SpeechPcmPlaybackMetrics = {
      mode: "pcm-stream",
      playback_id: playbackId,
    };
    let player: PcmStreamPlayer | null = null;
    let serverMetadataRead = false;
    const streamAbortController = new AbortController();
    const abortStream = () => streamAbortController.abort();
    if (signal.aborted) {
      abortStream();
    } else {
      signal.addEventListener("abort", abortStream, { once: true });
    }
    const playerPromise = PcmStreamPlayer.create({
      sourceSampleRate: 24000,
      initialBufferMs: 60,
      onPlaying: () => {
        if (requestIdRef.current !== requestId) {
          return;
        }
        setStatus("playing");
        metrics.tap_to_audio_playing_ms = roundedMilliseconds(nowMilliseconds() - tapStartedAt);
        metrics.underrun_count = player?.underrunCount || 0;
        reportSpeechPlaybackMetrics(providerAppId, { ...metrics, outcome: "playing" });
      },
    });
    const requestStartedAt = nowMilliseconds();
    metrics.tap_to_request_ms = roundedMilliseconds(requestStartedAt - tapStartedAt);
    let firstBrowserChunkSeen = false;
    let prefetchLimit = 1;

    function fillPrefetchQueue() {
      while (nextChunkIndex < chunks.length && prefetchedChunks.size < prefetchLimit) {
        const index = nextChunkIndex;
        nextChunkIndex += 1;
        const promise = synthesizeStreamChunkWithFallback(chunks[index], requestId, language, streamAbortController.signal);
        void promise.catch(() => undefined);
        prefetchedChunks.set(index, promise);
      }
    }

    fillPrefetchQueue();
    try {
      player = await playerPromise;
      pcmPlayerRef.current = player;
      if (requestIdRef.current !== requestId) {
        player.stop();
        pcmPlayerRef.current = null;
        return;
      }
      for (let index = 0; index < chunks.length; index += 1) {
        if (requestIdRef.current !== requestId) {
          return;
        }
        const prefetched = prefetchedChunks.get(index);
        if (!prefetched) {
          throw new Error("Speech stream prefetch queue lost a chunk.");
        }
        const responses = await prefetched;
        prefetchedChunks.delete(index);
        for (const response of responses) {
          const sampleRate = Number(response.headers.get("X-Audio-Sample-Rate") || "24000");
          const channels = Number(response.headers.get("X-Audio-Channels") || "1");
          const sampleFormat = response.headers.get("X-Audio-Sample-Format") || "s16le";
          if (!Number.isFinite(sampleRate) || sampleRate <= 0 || channels !== 1 || sampleFormat !== "s16le") {
            throw new Error("Speech provider returned an unsupported PCM stream description.");
          }
          if (!serverMetadataRead) {
            serverMetadataRead = true;
            metrics.generation_id = response.headers.get("X-Generation-Id") || undefined;
            Object.assign(metrics, parseSpeechServerTiming(response.headers.get("Server-Timing") || ""));
          }
          if (sampleRate !== player.decoder.sourceSampleRate) {
            throw new Error("Speech provider changed PCM sample rate between chunks.");
          }
          const reader = response.body?.getReader();
          if (!reader) {
            throw new Error("Speech provider returned an empty PCM stream.");
          }
          while (true) {
            const { done, value } = await reader.read();
            if (done) {
              break;
            }
            if (!firstBrowserChunkSeen) {
              firstBrowserChunkSeen = true;
              metrics.browser_first_chunk_ms = roundedMilliseconds(nowMilliseconds() - requestStartedAt);
              prefetchLimit = TTS_PREFETCH_CONCURRENCY;
              fillPrefetchQueue();
            }
            player.append(value);
          }
        }
        fillPrefetchQueue();
      }
      await player.finish();
      metrics.underrun_count = player.underrunCount;
      reportSpeechPlaybackMetrics(providerAppId, { ...metrics, outcome: "completed" });
      player.stop();
      pcmPlayerRef.current = null;
    } catch (error) {
      abortStream();
      throw error;
    } finally {
      signal.removeEventListener("abort", abortStream);
    }
  }

  async function synthesizeStreamChunkWithFallback(
    chunk: string,
    requestId: number,
    language: string,
    signal: AbortSignal,
  ): Promise<Response[]> {
    try {
      return [await synthesizeSpeechStream(providerAppId, chunk, language ? { language, signal } : { signal })];
    } catch (error) {
      if (signal.aborted) {
        throw error;
      }
      const retryChunks = retrySpeechChunks(chunk);
      if (isSplittableSynthesisError(error) && retryChunks.length > 1) {
        const responses: Response[] = [];
        for (const retryChunk of retryChunks) {
          if (requestIdRef.current !== requestId) {
            return responses;
          }
          responses.push(...(await synthesizeStreamChunkWithFallback(retryChunk, requestId, language, signal)));
        }
        return responses;
      }
      throw error;
    }
  }

  function failPlayback(requestId: number, message: string) {
    if (requestIdRef.current !== requestId) {
      return;
    }
    selfActivationRef.current = false;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    pcmPlayerRef.current?.stop();
    pcmPlayerRef.current = null;
    setErrorMessage(message);
    setStatus("error");
    clearActiveMessage(onActiveMessageChange, messageId);
    releaseAudioUrl();
  }

  function completePlayback(requestId: number) {
    if (requestIdRef.current !== requestId) {
      return;
    }
    selfActivationRef.current = false;
    abortControllerRef.current = null;
    audioRef.current = null;
    pcmPlayerRef.current?.stop();
    pcmPlayerRef.current = null;
    releaseAudioUrl();
    setErrorMessage("");
    setStatus("idle");
    clearActiveMessage(onActiveMessageChange, messageId);
  }

  function stopPlayback() {
    requestIdRef.current += 1;
    selfActivationRef.current = false;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    const audio = audioRef.current;
    audio?.pause();
    if (audio?.onended) {
      audio.onended.call(audio, new Event("ended"));
    }
    audioRef.current = null;
    pcmPlayerRef.current?.stop();
    pcmPlayerRef.current = null;
    releaseAudioUrl();
    setErrorMessage("");
    setStatus("idle");
  }

  function releaseAudioUrl() {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }

  function audioUrlFromResult(result: SpeechAudioResult) {
    if (result.audio_data_url) {
      return result.audio_data_url;
    }
    if (!result.audio_base64) {
      throw new Error("Speech provider did not return audio.");
    }
    const binary = Uint8Array.from(atob(result.audio_base64), (char) => char.charCodeAt(0));
    const blob = new Blob([binary], { type: result.content_type || "audio/wav" });
    const objectUrl = URL.createObjectURL(blob);
    objectUrlRef.current = objectUrl;
    return objectUrl;
  }

  async function synthesizeChunkWithFallback(
    chunk: string,
    requestId: number,
    language: string,
    signal: AbortSignal,
  ): Promise<SpeechAudioResult[]> {
    try {
      return [await synthesizeSpeechChunk(providerAppId, chunk, language, signal)];
    } catch (error) {
      if (signal.aborted) {
        throw error;
      }
      const retryChunks = retrySpeechChunks(chunk);
      if (isSplittableSynthesisError(error) && retryChunks.length > 1) {
        const results: SpeechAudioResult[] = [];
        for (const retryChunk of retryChunks) {
          if (requestIdRef.current !== requestId) {
            return results;
          }
          results.push(...(await synthesizeChunkWithFallback(retryChunk, requestId, language, signal)));
        }
        return results;
      }
      throw error;
    }
  }

  async function playSynthesizedChunk(result: SpeechAudioResult, requestId: number, onPlaying?: () => void) {
    const audioUrl = audioUrlFromResult(result);
    const audio = new Audio(audioUrl);
    audioRef.current = audio;
    audio.preload = "auto";
    audio.setAttribute("playsinline", "true");
    audio.load();
    const completion = audioCompletion(audio);
    try {
      await playAudioWithTimeout(audio);
      if (requestIdRef.current !== requestId) {
        completion.cancel();
        return;
      }
      setStatus("playing");
      onPlaying?.();
      await completion.promise;
    } catch (error) {
      completion.cancel();
      throw error;
    }
    if (requestIdRef.current === requestId) {
      audioRef.current = null;
      releaseAudioUrl();
    }
  }

  return (
    <>
      <button
        aria-label={isReading ? "Stop reading response" : "Read response aloud"}
        aria-pressed={isReading}
        className={`chatapp-message-action chatapp-message-action--icon chatapp-message-action--speech ${
          isReading ? "is-speaking" : ""
        } ${status === "loading" ? "is-loading" : ""} ${status === "error" ? "is-error" : ""}`}
        onClick={toggleSpeech}
        title={status === "error" ? errorMessage || "Speech unavailable" : isReading ? "Stop reading" : "Read aloud"}
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">
          {status === "loading" ? "hourglass_empty" : isReading ? "stop_circle" : "volume_up"}
        </span>
      </button>
      {status === "error" && errorMessage ? (
        <span className="chatapp-message-speech-error" role="alert">
          {errorMessage}
        </span>
      ) : null}
    </>
  );
}

function clearActiveMessage(onActiveMessageChange: Dispatch<SetStateAction<string | null>>, messageId: string) {
  onActiveMessageChange((currentMessageId) => (currentMessageId === messageId ? null : currentMessageId));
}

function synthesizeSpeechChunk(providerAppId: string, chunk: string, language: string, signal: AbortSignal): Promise<SpeechAudioResult> {
  return synthesizeSpeech(providerAppId, chunk, language ? { language, signal } : { signal });
}

function nowMilliseconds(): number {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

function roundedMilliseconds(value: number): number {
  return Math.round(Math.max(0, value) * 1000) / 1000;
}

function reportSpeechPlaybackMetrics(providerAppId: string, metrics: SpeechPcmPlaybackMetrics): void {
  publishSpeechPlaybackMetrics(metrics);
  void recordSpeechPlaybackMetrics(providerAppId, { ...metrics }).catch(() => undefined);
}

function createSpeechPlaybackId(): string {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  if (randomUuid) {
    return randomUuid;
  }
  return `browser-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
}

function speechPlaybackFailureCode(error: unknown): string {
  if (error instanceof DOMException && error.name) {
    return error.name.toLowerCase().replace(/[^a-z0-9._:-]+/g, "-").slice(0, 64) || "dom-exception";
  }
  return "playback-failed";
}
