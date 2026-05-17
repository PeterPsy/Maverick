import type { Dispatch, SetStateAction } from "react";
import { useEffect } from "react";
import { useSpeech } from "react-text-to-speech";

type MessageSpeechButtonProps = {
  activeMessageId: string | null;
  content: string;
  messageId: string;
  onActiveMessageChange: Dispatch<SetStateAction<string | null>>;
};

const SPEECH_CHUNK_SIZE = 280;

export function MessageSpeechButton(props: MessageSpeechButtonProps) {
  const speechText = speechTextFromMarkdown(props.content);

  if (!speechText || !supportsBrowserSpeechSynthesis()) {
    return null;
  }

  return <SupportedMessageSpeechButton {...props} speechText={speechText} />;
}

function SupportedMessageSpeechButton({
  activeMessageId,
  messageId,
  onActiveMessageChange,
  speechText,
}: MessageSpeechButtonProps & { speechText: string }) {
  const { speechStatus, start, stop } = useSpeech({
    text: speechText,
    stableText: true,
    preserveUtteranceQueue: false,
    maxChunkSize: SPEECH_CHUNK_SIZE,
    onStart: () => onActiveMessageChange(messageId),
    onStop: () => clearActiveMessage(onActiveMessageChange, messageId),
    onError: () => clearActiveMessage(onActiveMessageChange, messageId),
  });
  const isReading = activeMessageId === messageId && speechStatus !== "stopped";

  useEffect(() => {
    if (activeMessageId !== messageId && speechStatus !== "stopped") {
      stop();
    }
  }, [activeMessageId, messageId, speechStatus, stop]);

  function toggleSpeech() {
    if (isReading) {
      stop();
      clearActiveMessage(onActiveMessageChange, messageId);
      return;
    }

    onActiveMessageChange(messageId);
    start();
  }

  return (
    <button
      aria-label={isReading ? "Stop reading response" : "Read response aloud"}
      aria-pressed={isReading}
      className={`chatapp-message-action chatapp-message-action--icon chatapp-message-action--speech ${
        isReading ? "is-speaking" : ""
      }`}
      onClick={toggleSpeech}
      title={isReading ? "Stop reading" : "Read aloud"}
      type="button"
    >
      <span aria-hidden="true" className="material-symbols-rounded">
        {isReading ? "stop_circle" : "volume_up"}
      </span>
    </button>
  );
}

function supportsBrowserSpeechSynthesis() {
  return (
    typeof window !== "undefined" &&
    typeof window.speechSynthesis !== "undefined" &&
    typeof window.SpeechSynthesisUtterance !== "undefined"
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
