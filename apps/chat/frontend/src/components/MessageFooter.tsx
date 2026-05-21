import type { ReactNode } from "react";

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
  onCopy: (content: string) => Promise<void>;
  speechControl?: ReactNode;
}) {
  return (
    <div className="chatapp-message-mobile-footer">
      {content ? (
        <button
          aria-label="Copy message"
          className="chatapp-message-action chatapp-message-action--icon chatapp-message-action--copy"
          onClick={() => void onCopy(content)}
          title="Copy"
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-rounded">
            content_copy
          </span>
        </button>
      ) : null}
      {speechControl}
      <time className="chatapp-bubble__time" dateTime={createdAt}>
        {formatMessageTime(createdAt)}
      </time>
    </div>
  );
}
