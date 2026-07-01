import type { ReactNode } from "react";
import { CopyMessageButton, type CopyMessageHandler } from "./MessageCopyButton";

export function formatMessageTime(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

export function MessageFooter({
  content,
  createdAt,
  onCopy,
  speechControl,
}: {
  content: string;
  createdAt: string;
  onCopy: CopyMessageHandler;
  speechControl?: ReactNode;
}) {
  return (
    <div className="chatapp-message-mobile-footer">
      {content ? (
        <CopyMessageButton content={content} onCopyMessage={onCopy} />
      ) : null}
      {speechControl}
      <time className="chatapp-bubble__time" dateTime={createdAt}>
        {formatMessageTime(createdAt)}
      </time>
    </div>
  );
}
