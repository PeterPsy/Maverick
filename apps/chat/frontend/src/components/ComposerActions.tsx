import type { ReactNode } from "react";

export function ComposerActions({
  canSend,
  canStopTurn,
  hasDraft,
  dictationControl,
  onStopTurn,
  onSubmit,
}: {
  canSend: boolean;
  canStopTurn: boolean;
  hasDraft: boolean;
  dictationControl?: ReactNode;
  onStopTurn: () => void;
  onSubmit: () => void;
}) {
  const isStop = canStopTurn && !hasDraft;
  return (
    <div className="chatapp-composer__actions">
      {dictationControl}
      <button
        aria-label={isStop ? "Stop chat" : "Send message"}
        className={`chatapp-composer__icon-action ${isStop ? "is-stop" : "is-send"}`}
        disabled={!isStop && !canSend}
        onClick={isStop ? onStopTurn : onSubmit}
        title={isStop ? "Stop chat" : "Send"}
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">
          {isStop ? "stop_circle" : "send"}
        </span>
        <span className={isStop ? "chatapp-composer__stop-label" : "chatapp-composer__send-label"}>
          {isStop ? "Stop chat" : "Send"}
        </span>
      </button>
    </div>
  );
}
