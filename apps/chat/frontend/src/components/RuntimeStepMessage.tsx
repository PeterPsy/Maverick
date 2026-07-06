import type { RuntimeStepMessage as RuntimeStep } from "../api/client";

const FINAL_INTER_AGENT_SUMMARY_KINDS = new Set(["completed", "failed", "cancelled"]);

export function RuntimeStepMessage({
  liveInterAgentRunIds = new Set(),
  onOpenInterAgentGraph,
  openedInterAgentGraphRunIds = new Set(),
  step,
}: {
  liveInterAgentRunIds?: ReadonlySet<string>;
  onOpenInterAgentGraph?: (runId: string) => void;
  openedInterAgentGraphRunIds?: ReadonlySet<string>;
  step: RuntimeStep;
}) {
  const summaryRunId = interAgentSummaryRunId(step);
  const finalRunId = interAgentFinalSummaryRunId(step);
  const isLiveBoard = Boolean(summaryRunId && liveInterAgentRunIds.has(summaryRunId));
  const boardRunId = isLiveBoard ? summaryRunId : finalRunId;
  const isPendingBoard = Boolean(boardRunId && !isLiveBoard && !openedInterAgentGraphRunIds.has(boardRunId));
  return (
    <div className="chatapp-agent-step chatapp-agent-step--thought">
      <div className="chatapp-agent-step__body">
        <p>{step.label}</p>
        {boardRunId && onOpenInterAgentGraph ? (
          <button
            aria-label={isPendingBoard ? "Open pending multi-agent board" : "Open multi-agent board"}
            className={`chatapp-agent-step__board ${isLiveBoard ? "is-live" : ""} ${isPendingBoard ? "is-pending" : ""}`}
            onClick={() => onOpenInterAgentGraph(boardRunId)}
            title={isLiveBoard ? "Live multi-agent board" : isPendingBoard ? "Pending review" : "Open multi-agent board"}
            type="button"
          >
            {isLiveBoard ? <LiveBoardButtonGlow /> : null}
            <span aria-hidden="true" className="material-symbols-rounded chatapp-agent-step__board-icon">
              account_tree
            </span>
            <span className="chatapp-agent-step__board-label">Open multi-agent board</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function interAgentSummaryRunId(step: RuntimeStep): string {
  const detail = step.detail || {};
  const stepKind = typeof detail.step_kind === "string" ? detail.step_kind : "";
  const runId = typeof detail.inter_agent_run_id === "string" ? detail.inter_agent_run_id.trim() : "";
  if (stepKind !== "inter_agent_summary" || !runId) {
    return "";
  }
  return runId;
}

export function interAgentFinalSummaryRunId(step: RuntimeStep): string {
  const detail = step.detail || {};
  const summaryKind = typeof detail.summary_kind === "string" ? detail.summary_kind : "";
  const runId = interAgentSummaryRunId(step);
  if (!FINAL_INTER_AGENT_SUMMARY_KINDS.has(summaryKind)) {
    return "";
  }
  return runId;
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
