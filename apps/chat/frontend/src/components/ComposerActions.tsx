import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";

function keepActionTargetStable(event: ReactPointerEvent<HTMLButtonElement>) {
  // Preserve the current focus/layout until click, as the utility trigger does.
  // Otherwise the compact composer moves Send/Stop between pointer-down and up.
  event.preventDefault();
}

export function ComposerActions({
  canSend,
  canStopTurn,
  dictationControl,
  onStopTurn,
  onSubmit,
}: {
  canSend: boolean;
  canStopTurn: boolean;
  dictationControl?: ReactNode;
  onStopTurn: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="chatapp-composer__actions">
      {canStopTurn ? (
        <button
          aria-label="Stop chat"
          className="chatapp-composer__icon-action is-stop"
          onClick={onStopTurn}
          onPointerDown={keepActionTargetStable}
          title="Stop chat"
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-rounded">
            stop_circle
          </span>
          <span className="chatapp-composer__stop-label">Stop chat</span>
        </button>
      ) : null}
      {dictationControl}
      <button
        aria-label="Send message"
        className="chatapp-composer__icon-action is-send"
        disabled={!canSend}
        onClick={onSubmit}
        onPointerDown={keepActionTargetStable}
        title="Send"
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
