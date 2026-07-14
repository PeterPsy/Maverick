import type { Dispatch, SetStateAction } from "react";
import { useEffect, useRef, useState } from "react";
import { synthesizeSpeech } from "../api/client";
import {
  isSplittableSynthesisError,
  retrySpeechChunks,
  speechChunks,
  speechLanguageHint,
  speechLanguageTextFromMarkdown,
  speechTextFromMarkdown,
} from "../lib/messageSpeech";
import { audioCompletion, playAudioWithTimeout, speechPlaybackErrorMessage } from "../lib/speechAudioPlayback";

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
  speechText,
  maxTextChars = 0,
}: MessageSpeechButtonProps & { speechText: string }) {
  const [status, setStatus] = useState<SpeechPlaybackStatus>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);
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
    let nextChunkIndex = 0;
    const prefetchedChunks = new Map<number, Promise<SpeechAudioResult[]>>();

    function fillPrefetchQueue() {
      while (nextChunkIndex < chunks.length && prefetchedChunks.size < TTS_PREFETCH_CONCURRENCY) {
        const index = nextChunkIndex;
        nextChunkIndex += 1;
        const promise = synthesizeChunkWithFallback(chunks[index], requestId, language, abortController.signal);
        void promise.catch(() => undefined);
        prefetchedChunks.set(index, promise);
      }
    }

    try {
      fillPrefetchQueue();
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
          await playSynthesizedChunk(result, requestId);
        }
      }
      completePlayback(requestId);
    } catch (error) {
      if (requestIdRef.current === requestId) {
        failPlayback(requestId, speechPlaybackErrorMessage(error));
      }
    }
  }

  function failPlayback(requestId: number, message: string) {
    if (requestIdRef.current !== requestId) {
      return;
    }
    selfActivationRef.current = false;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
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

  async function playSynthesizedChunk(result: SpeechAudioResult, requestId: number) {
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
