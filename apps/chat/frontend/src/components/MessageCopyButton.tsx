import { useEffect, useRef, useState } from "react";

export type CopyMessageHandler = (content: string) => Promise<boolean>;

const COPIED_RESET_DELAY_MS = 1600;

export function CopyMessageButton({
  content,
  meta = false,
  onCopyMessage,
}: {
  content: string;
  meta?: boolean;
  onCopyMessage: CopyMessageHandler;
}) {
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);

  function clearResetTimer() {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
  }

  useEffect(() => {
    return clearResetTimer;
  }, []);

  useEffect(() => {
    setCopied(false);
    clearResetTimer();
  }, [content]);

  async function handleCopy() {
    let didCopy = false;
    try {
      didCopy = await onCopyMessage(content);
    } catch {
      didCopy = false;
    }
    if (!didCopy) {
      return;
    }
    setCopied(true);
    clearResetTimer();
    resetTimerRef.current = window.setTimeout(() => {
      resetTimerRef.current = null;
      setCopied(false);
    }, COPIED_RESET_DELAY_MS);
  }

  return (
    <button
      aria-label={copied ? "Message copied" : "Copy message"}
      className={`chatapp-message-action chatapp-message-action--icon chatapp-message-action--copy ${
        copied ? "is-copied" : ""
      } ${meta ? "chatapp-message-action--copy-meta" : ""}`}
      onClick={() => void handleCopy()}
      title={copied ? "Copied" : "Copy"}
      type="button"
    >
      <span aria-hidden="true" className="material-symbols-rounded">
        {copied ? "done" : "content_copy"}
      </span>
    </button>
  );
}
