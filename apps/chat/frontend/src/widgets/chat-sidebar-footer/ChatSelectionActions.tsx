import "./selection-actions.css";

export function ChatSelectionActions({ count, isDeleting, isConfirming, onRequest, onConfirm, onCancel }: {
  count: number;
  isDeleting: boolean;
  isConfirming: boolean;
  onRequest: () => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return <>
    {isConfirming ? (
      <div className="bs-chat-sidebar-footer__confirm-actions" role="group" aria-label="Confirm chat deletion">
        <button className="bs-chat-sidebar-footer__confirm-button is-danger" disabled={isDeleting || !count} onClick={onConfirm} type="button">
          Conferma
        </button>
        <button className="bs-chat-sidebar-footer__confirm-button" disabled={isDeleting} onClick={onCancel} type="button">
          Annulla
        </button>
      </div>
    ) : null}
    <button
      aria-label={"Delete " + count + " selected chat" + (count === 1 ? "" : "s")}
      className="bs-chat-sidebar-footer__new-chat is-delete"
      disabled={isDeleting || !count}
      onClick={onRequest}
      type="button"
    >
      <TrashIcon />
      <span>Delete Chat</span>
    </button>
  </>;
}

function TrashIcon() {
  return (
    <svg
      aria-hidden="true"
      className="bs-chat-sidebar-footer__trash"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.9"
      viewBox="0 0 24 24"
    >
      <path d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3" />
    </svg>
  );
}
