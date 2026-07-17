import { LiveBorderGlow } from "./LiveBorderGlow";

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
      {state === "live" ? <LiveBorderGlow /> : null}
      <span aria-hidden="true" className="material-symbols-rounded chatapp-inter-agent-board-button__icon">
        account_tree
      </span>
      <span className="chatapp-inter-agent-board-button__label">Multi-agent board</span>
    </button>
  );
}
