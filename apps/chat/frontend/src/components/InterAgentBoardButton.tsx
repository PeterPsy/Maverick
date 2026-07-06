export type InterAgentBoardButtonState = "live" | "pending" | "normal";

export function InterAgentBoardButton({
  className = "",
  onOpen,
  runId,
  state,
}: {
  className?: string;
  onOpen?: (runId: string) => void;
  runId: string;
  state: InterAgentBoardButtonState;
}) {
  const classes = ["chatapp-inter-agent-board-button", `is-${state}`, className].filter(Boolean).join(" ");
  return (
    <button
      aria-label={state === "pending" ? "Open multi-agent board (pending)" : "Open multi-agent board"}
      className={classes}
      disabled={!onOpen}
      onClick={() => onOpen?.(runId)}
      type="button"
    >
      {state === "live" ? <LiveBoardButtonGlow /> : null}
      <span aria-hidden="true" className="material-symbols-rounded chatapp-inter-agent-board-button__icon">
        account_tree
      </span>
      <span className="chatapp-inter-agent-board-button__label">Open multi-agent board</span>
    </button>
  );
}

function LiveBoardButtonGlow() {
  return (
    <span aria-hidden="true" className="chatapp-live-board-glow">
      <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--outer" />
      <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--a" />
      <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--b" />
      <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--c" />
      <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--bright" />
      <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--rim" />
    </span>
  );
}
