import type { Dispatch, SetStateAction } from "react";
import { useEffect, useRef, useState } from "react";
import { synthesizeSpeech } from "../api/client";

const DEFAULT_TTS_CHUNK_CHARS = 450;
const INITIAL_TTS_CHUNK_CHARS = 180;
const MIN_RETRY_TTS_CHUNK_CHARS = 180;
const AUDIO_PLAY_START_TIMEOUT_MS = 8000;
const AUDIO_CHUNK_END_TIMEOUT_MS = 180000;

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
    const chunks = speechChunks(speechText, maxTextChars);
    let chunkIndex = 0;

    function synthesizeNextChunk(): Promise<SpeechAudioResult[]> | null {
      const chunk = chunks[chunkIndex];
      chunkIndex += 1;
      return chunk ? synthesizeChunkWithFallback(chunk, requestId) : null;
    }

    try {
      let prefetched = synthesizeNextChunk();
      while (prefetched) {
        if (requestIdRef.current !== requestId) {
          return;
        }
        setStatus(audioRef.current ? "playing" : "loading");
        const results = await prefetched;
        prefetched = synthesizeNextChunk();
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
    audioRef.current = null;
    releaseAudioUrl();
    setErrorMessage("");
    setStatus("idle");
    clearActiveMessage(onActiveMessageChange, messageId);
  }

  function stopPlayback() {
    requestIdRef.current += 1;
    selfActivationRef.current = false;
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

  async function synthesizeChunkWithFallback(chunk: string, requestId: number): Promise<SpeechAudioResult[]> {
    try {
      return [await synthesizeSpeech(providerAppId, chunk)];
    } catch (error) {
      const retryChunks = retrySpeechChunks(chunk);
      if (isSplittableSynthesisError(error) && retryChunks.length > 1) {
        const results: SpeechAudioResult[] = [];
        for (const retryChunk of retryChunks) {
          if (requestIdRef.current !== requestId) {
            return results;
          }
          results.push(...(await synthesizeChunkWithFallback(retryChunk, requestId)));
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
  );
}

function audioCompletion(audio: HTMLAudioElement): { cancel: () => void; promise: Promise<void> } {
  let timeout: number | null = null;
  let settled = false;
  const clearCompletion = () => {
    if (timeout !== null) {
      window.clearTimeout(timeout);
      timeout = null;
    }
  };
  const promise = new Promise<void>((resolve, reject) => {
    const finish = () => {
      if (settled) {
        return;
      }
      settled = true;
      clearCompletion();
      resolve();
    };
    const fail = (message: string) => {
      if (settled) {
        return;
      }
      settled = true;
      clearCompletion();
      reject(new Error(message));
    };
    audio.onended = finish;
    audio.onerror = () => fail("Browser audio playback failed.");
    timeout = window.setTimeout(() => fail("Audio playback did not finish."), AUDIO_CHUNK_END_TIMEOUT_MS);
    if (audio.ended) {
      finish();
    }
  });
  return {
    cancel: () => {
      settled = true;
      clearCompletion();
    },
    promise,
  };
}

function playAudioWithTimeout(audio: HTMLAudioElement): Promise<void> {
  const playback = audio.play();
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      reject(new Error("Audio playback did not start."));
    }, AUDIO_PLAY_START_TIMEOUT_MS);
    playback.then(
      () => {
        window.clearTimeout(timeout);
        resolve();
      },
      (error) => {
        window.clearTimeout(timeout);
        reject(error);
      },
    );
  });
}

function speechPlaybackErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    if (error.name === "NotAllowedError") {
      return "Browser blocked speech playback. Click read aloud again.";
    }
    return `Speech playback failed: ${error.message}`;
  }
  return "Speech playback failed.";
}

function clearActiveMessage(onActiveMessageChange: Dispatch<SetStateAction<string | null>>, messageId: string) {
  onActiveMessageChange((currentMessageId) => (currentMessageId === messageId ? null : currentMessageId));
}

export function speechChunks(text: string, maxTextChars = 0): string[] {
  const limit = maxTextChars > 0 ? Math.min(maxTextChars, DEFAULT_TTS_CHUNK_CHARS) : DEFAULT_TTS_CHUNK_CHARS;
  const initialLimit = Math.min(limit, INITIAL_TTS_CHUNK_CHARS);
  const normalized = text.trim();
  if (!normalized || normalized.length <= limit) {
    return normalized ? [normalized] : [];
  }
  const chunks = speechChunksWithLimit(normalized, limit);
  if (chunks.length > 1 && chunks[0].length > initialLimit) {
    return [...splitInitialSpeechChunk(chunks[0], initialLimit), ...chunks.slice(1)];
  }
  return chunks;
}

function speechChunksWithLimit(text: string, limit: number): string[] {
  const chunks: string[] = [];
  let current = "";
  for (const piece of speechPieces(text)) {
    const next = current ? `${current} ${piece}` : piece;
    if (next.length <= limit) {
      current = next;
      continue;
    }
    if (current) {
      chunks.push(current);
      current = "";
    }
    chunks.push(...hardSplitSpeechPiece(piece, limit));
  }
  if (current) {
    chunks.push(current);
  }
  return chunks;
}

function splitInitialSpeechChunk(text: string, limit: number): string[] {
  if (text.length <= limit) {
    return [text];
  }
  const splitAt = Math.max(text.lastIndexOf(" ", limit), Math.min(limit, text.length));
  return [text.slice(0, splitAt).trim(), text.slice(splitAt).trim()].filter(Boolean);
}

function speechPieces(text: string): string[] {
  return text
    .replace(/\n{2,}/g, ". ")
    .split(/(?<=[.!?])\s+/)
    .map((piece) => piece.trim())
    .filter(Boolean);
}

function hardSplitSpeechPiece(piece: string, limit: number): string[] {
  const chunks: string[] = [];
  let remaining = piece.trim();
  while (remaining.length > limit) {
    const splitAt = Math.max(remaining.lastIndexOf(" ", limit), Math.min(limit, remaining.length));
    chunks.push(remaining.slice(0, splitAt).trim());
    remaining = remaining.slice(splitAt).trim();
  }
  if (remaining) {
    chunks.push(remaining);
  }
  return chunks;
}

function retrySpeechChunks(text: string): string[] {
  if (text.length <= MIN_RETRY_TTS_CHUNK_CHARS) {
    return [text];
  }
  const midpoint = Math.floor(text.length / 2);
  const before = text.lastIndexOf(" ", midpoint);
  const after = text.indexOf(" ", midpoint);
  const splitAt = before >= MIN_RETRY_TTS_CHUNK_CHARS ? before : after > 0 ? after : midpoint;
  const left = text.slice(0, splitAt).trim();
  const right = text.slice(splitAt).trim();
  return [left, right].filter(Boolean);
}

function isSplittableSynthesisError(error: unknown): boolean {
  const message = error instanceof Error ? error.message.toLowerCase() : "";
  return (
    message.includes("synthesized audio exceeds") ||
    message.includes("response size limit") ||
    message.includes("text must contain at most") ||
    message.includes("max_text_chars")
  );
}

export function speechTextFromMarkdown(content: string) {
  return content
    .replace(/\r\n?/g, "\n")
    .replace(/```[^\n]*\n([\s\S]*?)```/g, "$1")
    .replace(/```([\s\S]*?)```/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\[ref:[^\]]+\]/g, "")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s{0,3}>\s?/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+[.)]\s+/gm, "")
    .replace(/^\s*\|?[\s:-]+\|[\s|:-]*$/gm, "")
    .replace(/\|/g, " ")
    .replace(MARKDOWN_STRONG_ASTERISK, "$1$2")
    .replace(MARKDOWN_EMPHASIS_ASTERISK, "$1$2")
    .replace(MARKDOWN_STRIKE, "$1$2")
    .replace(MARKDOWN_STRONG_UNDERSCORE, "$1$2")
    .replace(MARKDOWN_EMPHASIS_UNDERSCORE, "$1$2")
    .replace(/[ \t]+/g, " ")
    .replace(/^[ \t]+|[ \t]+$/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const MARKDOWN_STRONG_ASTERISK = /(^|[^\w*])\*\*([^\s*](?:[\s\S]*?[^\s*])?)\*\*(?=$|[^\w*])/g;
const MARKDOWN_EMPHASIS_ASTERISK = /(^|[^\w*])\*([^\s*](?:[^*\n]*?[^\s*])?)\*(?=$|[^\w*])/g;
const MARKDOWN_STRIKE = /(^|[^\w~])~~([^\s~](?:[\s\S]*?[^\s~])?)~~(?=$|[^\w~])/g;
const MARKDOWN_STRONG_UNDERSCORE =
  /(^|[^\w_])__(?!(?:init|name|main|file|doc|class|module|dict|repr|str|call|enter|exit|iter|next|len|new|del)__)([^\s_](?:[\s\S]*?[^\s_])?)__(?=$|[^\w_])/g;
const MARKDOWN_EMPHASIS_UNDERSCORE = /(^|[^\w_])_(?!_)([^\s_](?:[^_\n]*?[^\s_])?)_(?!_)(?=$|[^\w_])/g;
