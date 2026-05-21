export function CopyMessageButton({
  content,
  meta = false,
  onCopyMessage,
}: {
  content: string;
  meta?: boolean;
  onCopyMessage: (content: string) => Promise<void>;
}) {
  return (
    <button
      aria-label="Copy message"
      className={`chatapp-message-action chatapp-message-action--icon chatapp-message-action--copy ${meta ? "chatapp-message-action--copy-meta" : ""}`}
      onClick={() => void onCopyMessage(content)}
      title="Copy"
      type="button"
    >
      <span aria-hidden="true" className="material-symbols-rounded">
        content_copy
      </span>
    </button>
  );
}
