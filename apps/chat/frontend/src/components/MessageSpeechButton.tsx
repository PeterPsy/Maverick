import type { Dispatch, SetStateAction } from "react";
import { useEffect, useRef, useState } from "react";
import { synthesizeSpeech } from "../api/client";

type MessageSpeechButtonProps = {
  activeMessageId: string | null;
  content: string;
  maxTextChars?: number;
  messageId: string;
  onActiveMessageChange: Dispatch<SetStateAction<string | null>>;
  providerAvailable?: boolean;
  providerAppId: string;
};

type SpeechPlaybackStatus = "idle" | "loading" | "playing" | "error";

export function MessageSpeechButton(props: MessageSpeechButtonProps) {
  const speechText = speechTextFromMarkdown(props.content);

  if (!speechText || !props.providerAppId) {
    return null;
  }
  if (props.providerAvailable === false) {
    return <DisabledSpeechButton ariaLabel="Speech provider unavailable" title="Speech provider unavailable" />;
  }
  const maxTextChars = props.maxTextChars || 0;
  if (maxTextChars > 0 && speechText.length > maxTextChars) {
    return (
      <DisabledSpeechButton
        ariaLabel="Read response aloud unavailable: response is too long"
        title={`Speech supports up to ${maxTextChars} characters`}
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
}: MessageSpeechButtonProps & { speechText: string }) {
  const [status, setStatus] = useState<SpeechPlaybackStatus>("idle");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const requestIdRef = useRef(0);
  const isActive = activeMessageId === messageId;
  const isReading = isActive && (status === "loading" || status === "playing");

  useEffect(() => {
    if (!isActive && status !== "idle") {
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

    onActiveMessageChange(messageId);
    setStatus("loading");
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    try {
      const result = await synthesizeSpeech(providerAppId, speechText);
      if (requestIdRef.current !== requestId) {
        return;
      }
      const audioUrl = audioUrlFromResult(result);
      const audio = new Audio(audioUrl);
      audioRef.current = audio;
      audio.onended = () => {
        if (requestIdRef.current === requestId) {
          stopPlayback();
          clearActiveMessage(onActiveMessageChange, messageId);
        }
      };
      audio.onerror = () => {
        if (requestIdRef.current === requestId) {
          setStatus("error");
          clearActiveMessage(onActiveMessageChange, messageId);
          releaseAudioUrl();
        }
      };
      await audio.play();
      if (requestIdRef.current === requestId) {
        setStatus("playing");
      }
    } catch {
      if (requestIdRef.current === requestId) {
        setStatus("error");
        clearActiveMessage(onActiveMessageChange, messageId);
        releaseAudioUrl();
      }
    }
  }

  function stopPlayback() {
    requestIdRef.current += 1;
    audioRef.current?.pause();
    audioRef.current = null;
    releaseAudioUrl();
    setStatus("idle");
  }

  function releaseAudioUrl() {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }

  function audioUrlFromResult(result: { audio_data_url?: string; audio_base64?: string; content_type?: string }) {
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

  return (
    <button
      aria-label={isReading ? "Stop reading response" : "Read response aloud"}
      aria-pressed={isReading}
      className={`chatapp-message-action chatapp-message-action--icon chatapp-message-action--speech ${
        isReading ? "is-speaking" : ""
      } ${status === "loading" ? "is-loading" : ""} ${status === "error" ? "is-error" : ""}`}
      onClick={toggleSpeech}
      title={status === "error" ? "Speech unavailable" : isReading ? "Stop reading" : "Read aloud"}
      type="button"
    >
      <span aria-hidden="true" className="material-symbols-rounded">
        {status === "loading" ? "hourglass_empty" : isReading ? "stop_circle" : "volume_up"}
      </span>
    </button>
  );
}

function clearActiveMessage(onActiveMessageChange: Dispatch<SetStateAction<string | null>>, messageId: string) {
  onActiveMessageChange((currentMessageId) => (currentMessageId === messageId ? null : currentMessageId));
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
