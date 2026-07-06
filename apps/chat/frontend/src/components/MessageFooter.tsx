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
  leadingControl,
  onCopy,
  speechControl,
}: {
  content: string;
  createdAt: string;
  leadingControl?: ReactNode;
  onCopy: CopyMessageHandler;
  speechControl?: ReactNode;
}) {
  const className = ["chatapp-message-mobile-footer", leadingControl ? "has-leading-control" : ""].filter(Boolean).join(" ");

  return (
    <div className={className}>
      {leadingControl ? <div className="chatapp-message-mobile-footer__leading">{leadingControl}</div> : null}
      <div className="chatapp-message-mobile-footer__trailing">
        {content ? <CopyMessageButton content={content} onCopyMessage={onCopy} /> : null}
        {speechControl}
        <time className="chatapp-bubble__time" dateTime={createdAt}>
          {formatMessageTime(createdAt)}
        </time>
      </div>
    </div>
  );
}
