import type { ReactNode } from "react";

export function ComposerActions({
  canSend,
  canStopTurn,
  dictationControl,
  isSending,
  onStopTurn,
  onSubmit,
}: {
  canSend: boolean;
  canStopTurn: boolean;
  dictationControl?: ReactNode;
  isSending: boolean;
  onStopTurn: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="chatapp-composer__actions">
      {canStopTurn ? (
        <button aria-label="Stop chat" className="chatapp-composer__icon-action is-stop" onClick={onStopTurn} title="Stop chat" type="button">
          <span aria-hidden="true" className="material-symbols-rounded">
            stop_circle
          </span>
          <span className="chatapp-composer__stop-label">Stop chat</span>
        </button>
      ) : null}
      {dictationControl}
      <button
        aria-label={isSending ? "Queue message" : "Send message"}
        className="chatapp-composer__icon-action is-send"
        disabled={!canSend}
        onClick={onSubmit}
        title={isSending ? "Queue" : "Send"}
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">
          send
        </span>
        <span className="chatapp-composer__send-label">Send</span>
      </button>
    </div>
  );
}
